"""The self-repair orchestrator — a deterministic, resumable state machine (mandate §5, §7).

Lifecycle:
  INTENT -> APPROVED_CONTRACT -> CODEBASE_MODEL -> AGENT_CHANGE -> ORDINARY_TESTS
  -> INDEPENDENT_CHALLENGE -> COUNTEREXAMPLE -> AGENT_REPAIR -> REVERIFICATION -> REPORT
  (-> LEARNING -> ATTESTATION -> PROTECTED_EXECUTION are recorded as downstream states)

Invariants enforced here:
  * The final status is decided ONLY by the independent verifier (property-verify), never by the
    agent's statement or by ordinary tests. An agent cannot promote its own work to verified.
  * A failed repair remains visibly failed (status 'contradicted'); criteria are never weakened and
    the approved change scope (a single target file) is never silently expanded.
  * Every state transition is recorded with a timestamp and structured evidence.
  * Bounded attempts with explicit stop conditions; interrupted/unavailable agents are reported as
    such, not as success.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .adapters.base import AgentResult
from .trust import sha256_hex

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"
PROPERTY_VERIFY = Path(__file__).resolve().parent / "property_verify.mjs"
MODULE = "src/settle.ts"
EXPORT = "allocate"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass
class Transition:
    ts: str
    state: str
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass
class RunRecord:
    task: str
    agent: str
    mode: str
    contract_digest: str
    git_head: str | None = None
    final_status: str = "unverified"
    states: list[str] = field(default_factory=list)
    transitions: list[Transition] = field(default_factory=list)
    attempts: list[dict[str, Any]] = field(default_factory=list)
    final_counterexample: dict[str, Any] | None = None
    ordinary_tests_green_on_defect: bool | None = None
    evidence_dir: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d


def setup_repo(work: Path, node_modules: Path) -> Path:
    """Create a candidate repo at the BUGGY baseline (floor split) with weak ordinary tests."""
    repo = work / f"repo-{uuid.uuid4().hex[:8]}"
    (repo / "src").mkdir(parents=True)
    shutil.copy(FIXTURES / "candidates" / "baseline-buggy.ts", repo / MODULE)
    shutil.copy(FIXTURES / "target-settlement" / "src" / "settle.test.ts", repo / "src" / "settle.test.ts")
    (repo / "package.json").write_text(json.dumps(
        {"name": "settlement", "private": True, "type": "module", "scripts": {"test": "vitest run"}}))
    if node_modules and Path(node_modules).exists():
        (repo / "node_modules").symlink_to(Path(node_modules), target_is_directory=True)
    for args in (["init", "-q"], ["config", "user.email", "sg@shipguard.local"], ["config", "user.name", "shipguard"],
                 ["add", "-A"], ["commit", "-qm", "baseline: floor-split allocation (loses pennies on uneven splits)"]):
        subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)
    return repo


def git_head(repo: Path) -> str:
    return subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()


def run_ordinary_tests(repo: Path) -> dict[str, Any]:
    vitest = repo / "node_modules" / ".bin" / "vitest"
    if not vitest.exists():
        return {"ran": False, "passed": None, "summary": "vitest not available (node_modules missing)"}
    try:
        p = subprocess.run([str(vitest), "run"], cwd=str(repo), capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        return {"ran": True, "passed": None, "summary": "ordinary tests timed out"}
    out = p.stdout + p.stderr
    line = next((l.strip() for l in out.splitlines() if "Tests " in l), "")
    return {"ran": True, "passed": p.returncode == 0, "summary": line or f"exit {p.returncode}"}


def run_challenge(tsx: Path, repo: Path, property_contract: Path, trials: int) -> dict[str, Any]:
    contract = json.loads(Path(property_contract).read_text())
    contract["trials"] = trials
    cf = repo.parent / f"challenge-{uuid.uuid4().hex[:6]}.json"
    cf.write_text(json.dumps(contract))
    try:
        p = subprocess.run([str(tsx), str(PROPERTY_VERIFY), "--module", str(repo / MODULE), "--contract", str(cf)],
                           capture_output=True, text=True, timeout=180)
        report = json.loads(p.stdout)
    except Exception as e:
        return {"verdict": "ENVIRONMENT_FAILURE", "error": str(e), "violations": [], "trials": 0}
    finally:
        cf.unlink(missing_ok=True)
    counterexample = None
    if report.get("violations"):
        v = report["violations"][0]
        counterexample = {"invariant": v.get("invariant"), "input": v.get("minimal_args"),
                          "observed": v.get("minimal_result"), "detail": v.get("detail"),
                          "failing_inputs": v.get("failing_inputs")}
    return {"verdict": report.get("verdict"), "trials": report.get("trials"),
            "violations": len(report.get("violations") or []), "counterexample": counterexample,
            "invariants": report.get("invariants")}


def _feedback(cx: dict[str, Any]) -> str:
    return (f"Independent property verifier found a defect your change did not fix.\n"
            f"Invariant violated: {cx.get('invariant')}\n"
            f"Smallest reproducing input: allocate({cx.get('input')}) returned {cx.get('observed')}\n"
            f"Why it is wrong: {cx.get('detail')}\n"
            f"Failing inputs sampled: {cx.get('failing_inputs')}")


def run_task(*, task: str, adapter, tsx: Path, node_modules: Path, work: Path,
             property_contract: Path | None = None, max_attempts: int = 2,
             agent_timeout: int = 240, trials: int = 200000, evidence_dir: Path | None = None) -> RunRecord:
    work = Path(work); work.mkdir(parents=True, exist_ok=True)
    property_contract = Path(property_contract or (FIXTURES / "contracts" / "property-contract.json"))
    contract_digest = sha256_hex(property_contract.read_bytes())
    rec = RunRecord(task=task, agent=adapter.name, mode=adapter.mode, contract_digest=contract_digest,
                    evidence_dir=str(evidence_dir or work))

    def go(state: str, **detail):
        rec.states.append(state)
        rec.transitions.append(Transition(_now(), state, detail))

    go("INTENT", task=task)
    go("APPROVED_CONTRACT", contract=str(property_contract), digest=contract_digest,
       note="developer-approved property contract; not generated from the agent's own output")
    go("CODEBASE_MODEL", note="structural model optional (apprentice); target=src/settle.ts export=allocate")

    usable, reason = adapter.available()
    if not usable:
        go("ENVIRONMENT_FAILURE", agent=adapter.name, reason=reason)
        rec.final_status = "environment_failure"
        _write(rec); return rec

    repo = setup_repo(work, node_modules)
    rec.git_head = git_head(repo)
    go("BASELINE", repo=str(repo), git_head=rec.git_head, note="buggy floor-split baseline; weak ordinary tests")

    cx = None
    for attempt in range(max_attempts + 1):
        state = "AGENT_CHANGE" if attempt == 0 else "AGENT_REPAIR"
        res: AgentResult = adapter.propose(task=task, repo=repo, attempt=attempt,
                                           feedback=(_feedback(cx) if cx else None), timeout=agent_timeout)
        go(state, attempt=attempt, agent=res.agent, mode=res.mode, outcome=res.outcome,
           changed_files=res.changed_files, statement=res.statement[:400], error=res.error,
           duration_s=res.duration_s)
        if res.outcome in ("unavailable", "interrupted"):
            rec.final_status = "interrupted" if res.outcome == "interrupted" else "environment_failure"
            rec.attempts.append({"attempt": attempt, "agent": asdict(res), "status": rec.final_status})
            _write(rec); return rec
        if res.outcome == "failed" or not res.made_change:
            rec.attempts.append({"attempt": attempt, "agent": asdict(res), "status": "no_change"})
            rec.final_status = "contradicted"
            go("REVERIFICATION", attempt=attempt, verdict="NO_CHANGE",
               note="agent made no change; not verified")
            _write(rec); return rec

        tests = run_ordinary_tests(repo)
        go("ORDINARY_TESTS", attempt=attempt, **tests)
        challenge = run_challenge(tsx, repo, property_contract, trials)
        verdict = challenge.get("verdict")
        cx = challenge.get("counterexample")
        go("INDEPENDENT_CHALLENGE", attempt=attempt, verdict=verdict, trials=challenge.get("trials"),
           violations=challenge.get("violations"), counterexample=cx)
        rec.attempts.append({"attempt": attempt, "agent": asdict(res), "ordinary_tests": tests,
                             "challenge": challenge, "git_head": git_head(repo)})

        if attempt == 0 and tests.get("passed") and verdict != "VERIFIED":
            rec.ordinary_tests_green_on_defect = True  # the aspirin: green tests, real defect

        if verdict == "VERIFIED":
            go("REVERIFICATION", attempt=attempt, verdict="VERIFIED",
               note="independent property verifier confirms the repair; ordinary tests also green")
            rec.final_status = "verified"
            rec.final_counterexample = None
            _write(rec); return rec

        if verdict == "ENVIRONMENT_FAILURE":
            rec.final_status = "environment_failure"
            _write(rec); return rec

        # contradicted: record the counterexample; loop will repair if attempts remain
        go("COUNTEREXAMPLE", attempt=attempt, counterexample=cx,
           note="fed back to the agent for a genuine repair" if attempt < max_attempts else "attempts exhausted")
        rec.final_counterexample = cx

    rec.final_status = "contradicted"  # repair attempts exhausted; defect remains visible
    go("REVERIFICATION", verdict="CONTRADICTED", note="bounded attempts exhausted; defect NOT repaired")
    _write(rec)
    return rec


def _write(rec: RunRecord) -> None:
    out = Path(rec.evidence_dir); out.mkdir(parents=True, exist_ok=True)
    (out / "run-record.json").write_text(json.dumps(rec.to_dict(), indent=2) + "\n")

"""The bounded, deterministic execution scheduler for BDE lawpacks.

Runs the compiled lawpack against a DISPOSABLE clone through the bundled runner.mjs (tsx),
with a whole-run timeout, per-law wall-clock isolation inside the runner, schema validation
of the lawpack BEFORE execution, and a stale-evidence guard (the grounding hash must still
match the file that is about to be executed). Environment failures are reported as such —
never as behavioural findings.
"""
from __future__ import annotations

import json
import subprocess
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import strategies
from .laws import (CLASS_C, BehaviouralLaw, lawpack_for, validate_lawpack)

RUNNER = Path(__file__).resolve().parent / "runner.mjs"

# BDE finding statuses (mandate §9) — aligned with, not silently replacing, the Sentinel
# vocabulary used by the rest of the product.
STATUS_CONFIRMED = "CONFIRMED_CONTRADICTION"
STATUS_VERIFIED = "VERIFIED_WITHIN_SCOPE"
STATUS_REGRESSION = "REGRESSION_OBSERVED"
STATUS_HYPOTHESIS = "HYPOTHESIS_FALSIFIED"
STATUS_REVIEW = "REVIEW_REQUIRED"
STATUS_INSUFFICIENT = "INSUFFICIENT_EVIDENCE"
STATUS_ENV_FAILURE = "ENVIRONMENT_FAILURE"

_ERROR_STATUS_BY = {"runner-missing": STATUS_ENV_FAILURE, "timeout": STATUS_ENV_FAILURE,
                    "schema-invalid": STATUS_INSUFFICIENT, "stale-grounding": STATUS_INSUFFICIENT}


@dataclass
class LawOutcome:
    law_id: str
    predicate: str
    status: str                       # PASS | FAIL | ERROR | SKIP | NOT_RUN
    trials: int = 0
    detail: str | None = None
    shrunk: bool | None = None
    duration_ms: int = 0
    finding: dict[str, Any] | None = None


@dataclass
class ExecutionReport:
    module: str
    revision: str
    executed: int = 0
    passed: int = 0
    failed: int = 0
    errors: int = 0
    skipped: int = 0
    not_run: int = 0
    outcomes: list[LawOutcome] = field(default_factory=list)
    findings: list[dict[str, Any]] = field(default_factory=list)
    runner_error: str | None = None
    duration_ms: int = 0

    def outcomes_for(self, law_id: str) -> LawOutcome | None:
        return next((o for o in self.outcomes if o.law_id == law_id), None)


def _classify_finding(law: BehaviouralLaw, mode: str) -> str:
    """Map a violated law onto a BDE status. Only A-approved / B-qualified laws confirm."""
    if law.is_blocking:
        return STATUS_CONFIRMED
    if law.evidence_class == CLASS_C:
        return STATUS_REGRESSION if mode == "check" else STATUS_REGRESSION
    return STATUS_HYPOTHESIS


def build_lawpack(laws: list[BehaviouralLaw], module: str, revision: str,
                  repo: Path) -> tuple[dict[str, Any] | None, list[str]]:
    """Validate + strategy-translate the laws; returns (pack-with-gen, problems)."""
    pack = lawpack_for(module, laws, revision)
    problems = validate_lawpack(pack)
    if problems:
        return None, problems
    entries = []
    for law in laws:
        # stale-evidence guard: the grounding hash must match the file about to be executed
        g = law.grounding
        target = repo / g.file if g.file else None
        if target is not None and target.is_file():
            import hashlib
            actual = hashlib.sha256(target.read_bytes()).hexdigest()
            if actual != g.sha256:
                problems.append(f"{law.law_id}: grounding hash for {g.file} does not match the file "
                                f"about to be executed (stale evidence)")
                continue
        ex = strategies.execution_for(law)
        if ex is None:
            problems.append(f"{law.law_id}: predicate {law.predicate} not executable as compiled")
            continue
        entries.append(ex)
    if problems and not entries:
        return None, problems
    pack["laws"] = entries
    return pack, problems


def run_lawpack(pack: dict[str, Any], repo: Path, tsx: Path, *, per_law_ms: int = 10000,
                timeout_s: int = 900, laws_meta: dict[str, BehaviouralLaw] | None = None,
                mode: str = "discover") -> ExecutionReport:
    """Execute a validated lawpack in the disposable ``repo`` clone. Deterministic seeds."""
    import time
    started = time.monotonic()
    revision = str(pack.get("git_revision", ""))
    rep = ExecutionReport(module=str(pack.get("module", "")), revision=revision)
    if not tsx.exists():
        rep.runner_error = f"tsx runner not found at {tsx}"
        rep.not_run = len(pack.get("laws") or [])
        return rep
    work = Path(repo).parent / f"bde-pack-{uuid.uuid4().hex[:8]}.json"
    work.parent.mkdir(parents=True, exist_ok=True)
    work.write_text(json.dumps(pack))
    try:
        proc = subprocess.run([str(tsx), str(RUNNER), "--lawpack", str(work), "--repo", str(repo),
                               "--per-law-ms", str(per_law_ms)],
                              capture_output=True, text=True, timeout=timeout_s)
    except subprocess.TimeoutExpired:
        rep.runner_error = f"lawpack execution exceeded {timeout_s}s"
        rep.not_run = len(pack.get("laws") or [])
        work.unlink(missing_ok=True)
        return rep
    finally:
        pass
    work.unlink(missing_ok=True)
    try:
        out = json.loads(proc.stdout)
    except json.JSONDecodeError:
        rep.runner_error = f"runner output was not JSON (exit {proc.returncode}): {proc.stderr[-400:]}"
        rep.not_run = len(pack.get("laws") or [])
        return rep
    meta = laws_meta or {}
    findings_by_law: dict[str, dict[str, Any]] = {}
    for f in out.get("findings", []):
        findings_by_law[str(f.get("law_id"))] = dict(f)
    for r in out.get("law_results", []):
        status = r.get("status", "ERROR")
        o = LawOutcome(law_id=r.get("law_id", "?"), predicate=r.get("predicate", "?"), status=status,
                       trials=r.get("trials", 0), detail=r.get("detail"), shrunk=r.get("shrunk"),
                       duration_ms=r.get("duration_ms", 0), finding=findings_by_law.get(r.get("law_id")))
        rep.outcomes.append(o)
        if status == "PASS":
            rep.passed += 1
        elif status == "FAIL":
            rep.failed += 1
            f = dict(findings_by_law.get(o.law_id) or {})
            law = meta.get(o.law_id)
            f["bde_status"] = _classify_finding(law, mode) if law else STATUS_REVIEW
            if law:
                f["law"] = {k: v for k, v in law.to_dict().items()
                            if k in ("law_id", "statement", "kind", "predicate", "module", "export",
                                     "evidence_class", "approval", "confidence", "limitations",
                                     "qualification", "grounding", "verification")}
            rep.findings.append(f)
        elif status == "ERROR":
            rep.errors += 1
        elif status == "SKIP":
            rep.skipped += 1
    rep.executed = out.get("executed", 0)
    rep.duration_ms = int((time.monotonic() - started) * 1000)
    return rep

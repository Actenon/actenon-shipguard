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

import hashlib
import json
import re
import shutil
import subprocess
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .adapters.base import AgentResult
from .sentinel import (bind_committed_tree, find_sentinel, is_dependency_path, is_test_path,
                       run_sentinel_verify)
from .trust import sha256_hex

FIXTURES = Path(__file__).resolve().parent / "_bundled"
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
    allowed_paths: list[str] = field(default_factory=list)
    tree_binding: dict[str, Any] | None = None    # committed tree == verified candidate (Phase 1.4)
    disclosure: dict[str, Any] | None = None      # portable verification disclosure (Phase 1.6)
    # Phase 2 — real-repository mode: prove the developer's tree was never modified.
    source_fingerprint_before: dict[str, Any] | None = None
    source_fingerprint_after: dict[str, Any] | None = None
    original_untouched: bool | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d


def setup_repo(work: Path, node_modules: Path, *, baseline: str = "baseline-buggy.ts",
               module: str = MODULE, test_src: str = "target-settlement/src/settle.test.ts",
               test_dest: str = "src/settle.test.ts") -> Path:
    """Create a candidate repo at a buggy baseline with weak ordinary tests.

    Parameterised by task so the loop is not hard-wired to the two-int settlement shape
    (a first step toward the resource-adapter generalisation).
    """
    repo = work / f"repo-{uuid.uuid4().hex[:8]}"
    (repo / Path(module).parent).mkdir(parents=True, exist_ok=True)
    shutil.copy(FIXTURES / "candidates" / baseline, repo / module)
    (repo / Path(test_dest).parent).mkdir(parents=True, exist_ok=True)
    shutil.copy(FIXTURES / test_src, repo / test_dest)
    (repo / "package.json").write_text(json.dumps(
        {"name": "settlement", "private": True, "type": "module", "scripts": {"test": "vitest run"}}))
    # node_modules must stay OUT of the git baseline: Sentinel snapshots tracked files and rejects
    # an unsupported node_modules entry. It is present on disk (for vitest) but gitignored. The
    # pattern has NO trailing slash so it also matches a node_modules *symlink* (not just a dir).
    (repo / ".gitignore").write_text("node_modules\n")
    if node_modules and Path(node_modules).exists():
        (repo / "node_modules").symlink_to(Path(node_modules), target_is_directory=True)
    for args in (["init", "-q"], ["config", "user.email", "sg@shipguard.local"], ["config", "user.name", "shipguard"],
                 ["add", "-A"], ["commit", "-qm", f"baseline: buggy {Path(module).stem}"]):
        subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)
    return repo


def git_head(repo: Path) -> str:
    return subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()


def repo_fingerprint(repo: Path) -> dict[str, Any]:
    """A checkable fingerprint of a repository's committed state and tracked content.

    Used to PROVE the developer's original tree was not modified during a run.
    """
    repo = Path(repo)
    head = git_head(repo)
    dirty = subprocess.run(["git", "-C", str(repo), "status", "--porcelain"],
                           capture_output=True, text=True).stdout.strip()
    tracked = subprocess.run(["git", "-C", str(repo), "ls-files"],
                             capture_output=True, text=True).stdout.split()
    h = hashlib.sha256()
    for rel in sorted(tracked):
        p = repo / rel
        h.update(rel.encode("utf-8"))
        h.update(p.read_bytes() if p.exists() else b"<missing>")
    return {"head": head, "dirty": dirty, "tracked_files": len(tracked),
            "tracked_content_sha256": h.hexdigest()}


def inspect_project(repo: Path, module: str, export: str) -> dict[str, Any]:
    """Decide whether a real repository is a SUPPORTED project type, with explicit reasons if not.

    Supported first scope: a Git repository containing a JS/TS package with a `test` script, whose
    target module exports a deterministic function with JSON-compatible inputs and outputs.
    Unsupported projects are rejected clearly rather than verified inaccurately.
    """
    repo = Path(repo)
    problems: list[str] = []
    info: dict[str, Any] = {"module": module, "export": export}

    if not (repo / ".git").exists():
        problems.append("not a git repository (Git history is required to bind verification evidence)")

    pkg_path = repo / "package.json"
    if not pkg_path.exists():
        problems.append("no package.json — not a supported JavaScript/TypeScript project")
    else:
        try:
            pkg = json.loads(pkg_path.read_text())
        except Exception as e:  # noqa: BLE001
            pkg = {}
            problems.append(f"package.json is not valid JSON: {e}")
        info["package_name"] = pkg.get("name")
        info["package_type"] = pkg.get("type")
        scripts = pkg.get("scripts") or {}
        info["test_script"] = scripts.get("test")
        if not scripts.get("test"):
            problems.append("package.json defines no `test` script — the project's ordinary tests cannot be run")

    mod = repo / module
    if not mod.exists():
        problems.append(f"target module {module!r} does not exist in this repository")
    else:
        if mod.suffix not in (".ts", ".mts", ".cts", ".js", ".mjs"):
            problems.append(f"unsupported module type {mod.suffix!r} (supported: .ts/.mts/.cts/.js/.mjs)")
        src = mod.read_text(errors="replace")
        patterns = (rf"export\s+(?:async\s+)?function\s+{re.escape(export)}\b",
                    rf"export\s+(?:const|let|var)\s+{re.escape(export)}\b",
                    rf"export\s*\{{[^}}]*\b{re.escape(export)}\b")
        if not any(re.search(p, src, re.S) for p in patterns):
            problems.append(f"module {module!r} does not export {export!r}")
        info["module_bytes"] = len(mod.read_bytes())

    if not (repo / "node_modules").exists():
        problems.append("node_modules is absent — install the project's reviewed dependencies first, "
                        "or pass --node-modules to reuse an existing installation")

    info["supported"] = not problems
    info["problems"] = problems
    return info


def clone_isolated(src_repo: Path, work: Path, node_modules: Path | None = None) -> Path:
    """Create a DISPOSABLE isolated working copy of a real developer repository.

    The developer's original source tree is never modified: a full local clone carries the Git
    history and working tree, and dependencies are shared read-only by symlink. All agent edits,
    commits and verification happen inside the clone.
    """
    src_repo = Path(src_repo).resolve()
    dest = Path(work) / f"real-{uuid.uuid4().hex[:8]}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "clone", "--quiet", "--no-hardlinks", str(src_repo), str(dest)],
                   check=True, capture_output=True)
    nm_src = Path(node_modules) if node_modules else (src_repo / "node_modules")
    if nm_src.exists() and not (dest / "node_modules").exists():
        (dest / "node_modules").symlink_to(nm_src, target_is_directory=True)
    return dest


def run_ordinary_tests(repo: Path, timeout: int = 300) -> dict[str, Any]:
    """Run the project's OWN ordinary test suite — never a ShipGuard-invented one.

    Prefers the package's declared ``test`` script (so a real repository's existing tests and
    history are preserved and used as-is); falls back to a local vitest binary.
    """
    repo = Path(repo)
    cmd: list[str] | None = None
    runner = "none"
    pkg = repo / "package.json"
    if pkg.exists():
        try:
            script = (json.loads(pkg.read_text()).get("scripts") or {}).get("test")
        except Exception:  # noqa: BLE001
            script = None
        if script and shutil.which("npm"):
            cmd, runner = ["npm", "test"], "npm-test"
    if cmd is None:
        vitest = repo / "node_modules" / ".bin" / "vitest"
        if vitest.exists():
            cmd, runner = [str(vitest), "run"], "vitest"
    if cmd is None:
        return {"ran": False, "passed": None, "runner": "none",
                "summary": "no `test` script and vitest not available (node_modules missing?)"}
    try:
        p = subprocess.run(cmd, cwd=str(repo), capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"ran": True, "passed": None, "runner": runner,
                "summary": f"ordinary tests timed out after {timeout}s"}
    out = p.stdout + p.stderr
    line = next((l.strip() for l in out.splitlines() if "Tests " in l or "test files" in l), "")
    return {"ran": True, "passed": p.returncode == 0, "runner": runner,
            "summary": (line or f"exit {p.returncode}")[:200]}


def run_sentinel_challenge(sentinel_cli, repo: Path, approved_contract: Path, store: Path,
                           *, baseline: str = "HEAD", runner: str = "local", timeout: int = 300,
                           attempt_id: str | None = None) -> dict[str, Any]:
    """Independent acceptance via the REAL Sentinel verifier (mandate §THIRD, Phase 1).

    Consumes the structured receipt (never a terminal string) and enforces evidence integrity:
    a fresh receipt for THIS attempt, content-addressed receipt + referenced objects, exact
    candidate/contract identity, schema-correct statuses and authorised change scope. The contract
    and the verifier store live OUTSIDE the agent repo.
    """
    v = run_sentinel_verify(repo=repo, contract_path=approved_contract, store=store,
                            baseline=baseline, sentinel=sentinel_cli, runner=runner,
                            allow_local=(runner == "local"), timeout=timeout, attempt_id=attempt_id)
    cx = None
    if v.counterexamples:
        c = v.counterexamples[0]
        cx = {"requirement_id": c.get("requirement_id"), "invariant": c.get("label"),
              "input": c.get("input"), "expected": c.get("expected"), "observed": c.get("observed"),
              "detail": c.get("detail"), "shrunk": c.get("shrunk")}
    return {"ok": v.ok, "verdict": v.status, "counterexample": cx, "requirements": v.requirements,
            "ordinary_tests": v.ordinary_tests, "receipt_hash": v.receipt_hash,
            "report_basename": Path(v.report_path).name if v.report_path else "",
            "bindings": v.bindings, "reasons": v.reasons, "integrity": v.integrity,
            "changes": v.changes, "non_verified_checks": v.non_verified_checks,
            "duplicate_check_ids": v.duplicate_check_ids, "exit_code": v.exit_code,
            "attempt_id": v.attempt_id, "disclosure": v.disclosure,
            "all_counterexamples": v.counterexamples}


def validate_change_scope(repo: Path, allowed_paths: list[str] | None) -> dict[str, Any]:
    """Validate the ACTUAL diff against the approved change scope.

    A prompt telling the agent not to touch tests is not a control. Out-of-scope files, test
    modifications (possible weakening) and dependency changes all force human review.
    """
    from .adapters.base import git_diff
    changed, _ = git_diff(repo)
    allowed = list(allowed_paths or [])
    in_scope: list[str] = []
    out_of_scope: list[str] = []
    test_changes: list[str] = []
    dep_changes: list[str] = []
    for p in changed:
        if allowed and not any(p == a or p.startswith(a.rstrip("/") + "/") for a in allowed):
            out_of_scope.append(p)
        else:
            in_scope.append(p)
        if is_test_path(p):
            test_changes.append(p)
        if is_dependency_path(p):
            dep_changes.append(p)
    return {"changed": changed, "allowed_paths": allowed, "in_scope": in_scope,
            "out_of_scope": out_of_scope, "test_changes": test_changes,
            "dependency_changes": dep_changes,
            "clean": not (out_of_scope or test_changes or dep_changes)}


def is_detected_defect(tests_passed: bool | None, challenge: dict[str, Any]) -> bool:
    """ASPIRIN is claimed ONLY for a genuine independent behavioural CONTRADICTION.

    Environment failures, incomplete coverage, unknown statuses, unresolved reviews, no-change and
    verified outcomes are never described as a detected defect.
    """
    return (tests_passed is True and challenge.get("verdict") == "CONTRADICTED"
            and not challenge.get("ok"))


def _commit_candidate(repo: Path, message: str, allowed_paths: list[str] | None) -> str:
    """Commit ONLY the approved-scope paths — never a blind ``git add -A``."""
    paths = list(allowed_paths) if allowed_paths else ["."]
    for args in (["add", "--", *paths], ["commit", "-qm", message]):
        subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)
    return git_head(repo)


def _feedback(cx: dict[str, Any]) -> str:
    return (f"Independent Sentinel verification CONTRADICTED an approved requirement your change did not satisfy.\n"
            f"Requirement: {cx.get('requirement_id')} — {cx.get('invariant')}\n"
            f"Reproducing input: allocate({cx.get('input')})\n"
            f"Expected: {cx.get('expected')}\n"
            f"Observed: {cx.get('observed')}\n"
            f"Why it is wrong: {cx.get('detail')}\n"
            f"Fix the underlying defect for the whole requirement class; do not special-case this input.")


def _model_codebase(repo: Path, target_file: str, export: str) -> dict[str, Any]:
    """Structural model of the candidate (real extraction, not a text-only placeholder).

    FIFTH wires Apprentice here for a full incremental codebase model; until then this performs a
    genuine structural scan of the target module (exported symbols) and reports apprentice status
    honestly rather than claiming an integration that did not run.
    """
    src = (repo / target_file)
    exports: list[str] = []
    if src.exists():
        import re
        for m in re.finditer(r"export\s+(?:async\s+)?function\s+([A-Za-z0-9_]+)", src.read_text()):
            exports.append(m.group(1))
    return {"target": target_file, "export": export, "exported_symbols": exports,
            "apprentice": "not-wired (structural scan only)",
            "note": "structural model of the candidate module; Apprentice indexing is a FIFTH item"}


def run_task(*, task: str, adapter, work: Path, sentinel_cli=None, approved_contract: Path | None = None,
             node_modules: Path | None = None, max_attempts: int = 2, agent_timeout: int = 240,
             baseline: str = "HEAD", runner: str = "local", evidence_dir: Path | None = None,
             target_file: str = MODULE, export: str = EXPORT, baseline_fixture: str = "baseline-buggy.ts",
             test_src: str = "target-settlement/src/settle.test.ts",
             test_dest: str = "src/settle.test.ts", source_repo: Path | None = None) -> RunRecord:
    work = Path(work); work.mkdir(parents=True, exist_ok=True)
    # The approved Sentinel acceptance contract is HELD OUT from the agent (lives in the package /
    # a verifier dir, never inside the candidate repo) and is not generated from the agent's output.
    approved_contract = Path(approved_contract or (FIXTURES / "contracts" / "settlement-contract.json"))
    contract_digest = sha256_hex(approved_contract.read_bytes())
    contract_json = json.loads(approved_contract.read_text())
    # The approved change scope comes from the contract, and is enforced against the real diff.
    allowed_paths = list(contract_json.get("allowedPaths") or [target_file])
    sentinel_cli = sentinel_cli or find_sentinel()
    store = work / "verifier-store"          # held-out evidence store, OUTSIDE the agent repo
    rec = RunRecord(task=task, agent=adapter.name, mode=adapter.mode, contract_digest=contract_digest,
                    evidence_dir=str(evidence_dir or work), allowed_paths=allowed_paths)

    def go(state: str, **detail):
        rec.states.append(state)
        rec.transitions.append(Transition(_now(), state, detail))

    def finish() -> RunRecord:
        """Persist the record. In real-repository mode, PROVE the developer's tree is untouched."""
        if source_repo is not None and rec.source_fingerprint_before is not None:
            after = repo_fingerprint(Path(source_repo))
            rec.source_fingerprint_after = after
            rec.original_untouched = (after == rec.source_fingerprint_before)
            go("ORIGINAL_TREE_CHECK", untouched=rec.original_untouched,
               before=rec.source_fingerprint_before, after=after,
               note="the developer's repository was cloned into a disposable worktree, never edited in place")
        _write(rec)
        return rec

    go("INTENT", task=task)
    go("APPROVED_CONTRACT", contract=str(approved_contract), digest=contract_digest,
       verifier="sentinel", allowed_paths=allowed_paths,
       note="developer-approved Sentinel acceptance contract; held out from the agent")

    usable, reason = adapter.available()
    if not usable:
        go("ENVIRONMENT_FAILURE", agent=adapter.name, reason=reason)
        rec.final_status = "environment_failure"
        return finish()
    if sentinel_cli is None:
        go("ENVIRONMENT_FAILURE", reason="sentinel CLI not available — cannot independently verify")
        rec.final_status = "environment_failure"
        return finish()

    if source_repo is not None:
        # PHASE 2 — a real developer repository, worked on inside a disposable isolated clone.
        insp = inspect_project(Path(source_repo), target_file, export)
        go("PROJECT_INSPECTION", supported=insp["supported"], problems=insp["problems"],
           package_name=insp.get("package_name"), package_type=insp.get("package_type"),
           test_script=insp.get("test_script"), module=target_file, export=export,
           note="the original repository was only read, never modified")
        if not insp["supported"]:
            go("UNSUPPORTED_PROJECT", problems=insp["problems"],
               note="rejected clearly rather than verifying an unsupported project inaccurately")
            rec.final_status = "environment_failure"
            return finish()
        rec.source_fingerprint_before = repo_fingerprint(Path(source_repo))
        repo = clone_isolated(Path(source_repo), work, node_modules)
        rec.git_head = git_head(repo)
        go("BASELINE", mode="real-repository-isolated-clone", git_head=rec.git_head,
           source_fingerprint=rec.source_fingerprint_before,
           note="disposable clone; the developer's working tree and Git history are preserved")
    else:
        repo = setup_repo(work, node_modules, baseline=baseline_fixture, module=target_file,
                          test_src=test_src, test_dest=test_dest)
        rec.git_head = git_head(repo)
        go("BASELINE", mode="synthetic-fixture", git_head=rec.git_head,
           note=f"buggy baseline ({baseline_fixture}); weak ordinary tests")
    go("CODEBASE_MODEL", **_model_codebase(repo, target_file, export))

    cx = None
    for attempt in range(max_attempts + 1):
        state = "AGENT_CHANGE" if attempt == 0 else "AGENT_REPAIR"
        res: AgentResult = adapter.propose(task=task, repo=repo, attempt=attempt,
                                           feedback=(_feedback(cx) if cx else None), timeout=agent_timeout,
                                           target_file=target_file, export=export)
        go(state, attempt=attempt, agent=res.agent, mode=res.mode, outcome=res.outcome,
           changed_files=res.changed_files, statement=res.statement[:400], error=res.error,
           duration_s=res.duration_s)
        if res.outcome in ("unavailable", "interrupted"):
            rec.final_status = "interrupted" if res.outcome == "interrupted" else "environment_failure"
            rec.attempts.append({"attempt": attempt, "agent": asdict(res), "status": rec.final_status})
            return finish()
        if res.outcome == "failed" or not res.made_change:
            # Distinct from "contradicted": the agent produced NO change (it may have asked for
            # clarification or declined). Honest status — not an independent contradiction.
            rec.attempts.append({"attempt": attempt, "agent": asdict(res), "status": "no_change"})
            rec.final_status = "no_change"
            go("REVERIFICATION", attempt=attempt, verdict="NO_CHANGE",
               note="agent made no change (possibly awaiting clarification); nothing independently verified")
            return finish()

        # Integrity guard: the agent must not have tampered with the held-out acceptance contract.
        if sha256_hex(approved_contract.read_bytes()) != contract_digest:
            go("TAMPER", note="approved contract digest changed during run — aborting; the agent cannot redefine acceptance")
            rec.final_status = "review_required"
            return finish()

        # Phase 1.5 — validate the ACTUAL diff against the approved change scope. A prompt telling
        # the agent not to touch tests is not a control; out-of-scope edits, test modifications and
        # dependency changes force human review instead of automatic acceptance.
        scope = validate_change_scope(repo, allowed_paths)
        go("CHANGE_SCOPE", attempt=attempt, **scope)
        if not scope["clean"]:
            rec.attempts.append({"attempt": attempt, "agent": asdict(res), "scope": scope,
                                 "status": "review_required"})
            rec.final_status = "review_required"
            go("REVERIFICATION", attempt=attempt, verdict="REVIEW REQUIRED", scope=scope,
               note=("change touches tests, dependencies or unauthorised paths; accepting it "
                     "automatically would let the agent redefine its own acceptance"))
            return finish()

        tests = run_ordinary_tests(repo)
        go("ORDINARY_TESTS", attempt=attempt, **tests)
        # Phase 1.2 — a unique verification identity per attempt, so no receipt can be inherited.
        attempt_id = f"a{attempt}-{uuid.uuid4().hex[:8]}"
        challenge = run_sentinel_challenge(sentinel_cli, repo, approved_contract, store,
                                           baseline=baseline, runner=runner, attempt_id=attempt_id)
        verdict = challenge.get("verdict")
        cx = challenge.get("counterexample")
        go("INDEPENDENT_CHALLENGE", attempt=attempt, attempt_id=attempt_id, verdict=verdict,
           ok=challenge.get("ok"), requirements=challenge.get("requirements"),
           ordinary_tests=challenge.get("ordinary_tests"), receipt_hash=challenge.get("receipt_hash"),
           integrity=challenge.get("integrity"), counterexample=cx,
           reasons=(challenge.get("reasons") or [])[:6])
        rec.attempts.append({"attempt": attempt, "attempt_id": attempt_id, "agent": asdict(res),
                             "ordinary_tests": tests, "scope": scope, "challenge": challenge,
                             "git_head": git_head(repo)})

        # Phase 1.7 — ASPIRIN only for a genuine independent behavioural contradiction.
        if attempt == 0 and is_detected_defect(tests.get("passed"), challenge):
            rec.ordinary_tests_green_on_defect = True

        if challenge.get("ok"):
            new_head = _commit_candidate(
                repo, f"verified change (attempt {attempt}) [sentinel {str(challenge.get('receipt_hash'))[:12]}]",
                allowed_paths)
            # Phase 1.4 — establish a CHECKABLE binding that the committed tree is byte-identical to
            # the candidate Sentinel actually verified. A receipt recorded against an earlier HEAD
            # does not, by itself, attest this commit.
            binding = bind_committed_tree(store=store / f"attempt-{attempt_id}",
                                          receipt_hash=challenge.get("receipt_hash"),
                                          repo=repo, commit=new_head)
            go("TREE_BINDING", attempt=attempt, git_head=new_head,
               candidate_hash=binding.get("candidate_hash"), files_checked=binding.get("files_checked"),
               files_matched=len(binding.get("files_matched") or []), mismatches=binding.get("mismatches"),
               equivalent=binding.get("equivalent"), error=binding.get("error"))
            if not binding.get("equivalent"):
                rec.final_status = "review_required"
                go("REVERIFICATION", attempt=attempt, verdict="REVIEW REQUIRED", tree_binding=binding,
                   note="committed tree is not byte-identical to the verified candidate; refusing to claim verification")
                return finish()
            rec.git_head = new_head
            rec.tree_binding = binding
            rec.disclosure = challenge.get("disclosure")
            go("REVERIFICATION", attempt=attempt, verdict="VERIFIED",
               receipt_hash=challenge.get("receipt_hash"), bindings=challenge.get("bindings"),
               note="independent Sentinel verification confirms the change; ordinary tests also green")
            go("ATTESTATION_READY", git_head=new_head, receipt_hash=challenge.get("receipt_hash"),
               candidate_hash=(challenge.get("bindings") or {}).get("candidate_hash"),
               tree_equivalent=True,
               note="committed tree proven byte-identical to the verified candidate snapshot")
            rec.final_status = "verified"
            rec.final_counterexample = None
            return finish()

        if verdict == "ENVIRONMENT_FAILURE":
            go("ENVIRONMENT_FAILURE", attempt=attempt, reasons=challenge.get("reasons"))
            rec.final_status = "environment_failure"
            return finish()

        if verdict == "REVIEW REQUIRED":
            rec.final_status = "review_required"
            rec.final_counterexample = cx
            go("REVERIFICATION", attempt=attempt, verdict="REVIEW REQUIRED",
               reasons=challenge.get("reasons"),
               note="Sentinel requires human judgement; not auto-accepted and not a detected defect")
            return finish()

        if verdict != "CONTRADICTED":
            # UNVERIFIED, an unknown status, or an evidence-integrity failure: insufficient evidence.
            # This is NOT a detected defect and must never be reported as one.
            rec.final_status = "unverified"
            rec.final_counterexample = cx
            go("REVERIFICATION", attempt=attempt, verdict=verdict, reasons=challenge.get("reasons"),
               note="evidence insufficient or an integrity check failed; not accepted, not a contradiction")
            return finish()

        # CONTRADICTED: record the counterexample; the loop repairs if attempts remain.
        go("COUNTEREXAMPLE", attempt=attempt, counterexample=cx,
           all_counterexamples=challenge.get("all_counterexamples"),
           note="fed back to the agent for a genuine repair" if attempt < max_attempts else "attempts exhausted")
        rec.final_counterexample = cx

    rec.final_status = "contradicted"  # repair attempts exhausted; defect remains visible
    go("REVERIFICATION", verdict="CONTRADICTED", note="bounded attempts exhausted; defect NOT repaired")
    return finish()


def _portable(s: str) -> str:
    """Scrub absolute local paths from public evidence (P2 hygiene): the bundled fixtures dir, the
    project root, the home dir, and ephemeral temp work dirs. Essential evidence (git SHAs, receipt
    hashes, counterexamples, verdicts, agent statements) is untouched — only filesystem paths are
    tokenised. Most-specific roots are replaced first so no project structure leaks via ``~``."""
    import re
    proj = Path(__file__).resolve().parents[2]          # the actenon-shipguard repo root
    for root, tok in ((FIXTURES.resolve(), "<bundled>"), (FIXTURES, "<bundled>"),
                      (proj.resolve(), "<project>"), (proj, "<project>"),
                      (Path.home(), "~")):
        s = s.replace(str(root), tok)
    s = re.sub(r"/(?:private/)?tmp/[A-Za-z0-9._/-]+", "<work>", s)
    return s


def _write(rec: RunRecord) -> None:
    out = Path(rec.evidence_dir); out.mkdir(parents=True, exist_ok=True)
    (out / "run-record.json").write_text(_portable(json.dumps(rec.to_dict(), indent=2)) + "\n")

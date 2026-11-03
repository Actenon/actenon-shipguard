"""The developer-facing BDE workflow: `shipguard discover` and `shipguard check`.

CONTRACT (mandate §8):

  * The developer's source repository is only ever READ. All execution happens in a
    disposable local clone (``clone_isolated`` — the same boundary as the v0.2.0 repair
    loop); the original tree's tracked content is fingerprinted before and after and the
    equality proof is recorded on the result.
  * Executing laws means running the project's own module code in a local subprocess.
    That is ADVISORY isolation (same OS user), exactly like Sentinel's ``local`` runner —
    stated, never overstated. Host repository intake requires explicit trust before Git
    or collection. ``--allow-host-intake`` permits compilation only; local execution
    additionally requires ``--allow-local`` or ``SHIPGUARD_ALLOW_LOCAL``. Local-execution
    consent also covers host intake. Docker never implies that host intake is safe.
  * The final statuses are the durable set from mandate §9, mapped onto (never silently
    replacing) the existing ShipGuard/Sentinel vocabulary.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..orchestrator import clone_isolated, git_head, repo_fingerprint
from .authority import AuthorityReport, Policy, annotate_section_arity, qualify
from .compiler import compile_laws
from .laws import BehaviouralLaw
from .scheduler import (
    STATUS_CONFIRMED,
    STATUS_ENV_FAILURE,
    STATUS_INSUFFICIENT,
    STATUS_VERIFIED,
    ExecutionReport,
    LawOutcome,
    build_lawpack,
    run_lawpack,
)
from .sources import EvidenceBundle, collect
from .witness import Finding, write_evidence


@dataclass
class BDEResult:
    mode: str                                   # "discover" | "check"
    module: str
    revision: str = ""
    tracked_files: int = 0
    original_untouched: bool | None = None
    laws_total: int = 0
    laws_blocking: int = 0
    laws_hypotheses: int = 0
    laws_preservation: int = 0
    executed: int = 0
    passed: int = 0
    failed: int = 0
    errors: int = 0
    skipped: int = 0
    not_run: int = 0
    outcomes: list[LawOutcome] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    overall_status: str = STATUS_INSUFFICIENT
    not_checked: list[dict[str, Any]] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    evidence_dir: str = ""
    clone_dir: str = ""                         # recorded for cleanup/debugging; never published absolute
    changed_files: list[str] = field(default_factory=list)
    changed_exports: list[str] = field(default_factory=list)
    duration_ms: int = 0
    execution_boundary: str = "not-executed"
    runtime_image: str | None = None
    source_sha256: str = ""
    lawpack_sha256: str = ""

    @property
    def exit_code(self) -> int:
        if self.overall_status in (STATUS_ENV_FAILURE,):
            return 2
        if self.overall_status in (STATUS_CONFIRMED, "REGRESSION_OBSERVED"):
            return 1
        return 0


def _consented(allow_local: bool) -> bool:
    return bool(allow_local or os.environ.get("SHIPGUARD_ALLOW_LOCAL") == "1")


def _find_tsx(explicit: str | None = None) -> Path | None:
    if explicit:
        return Path(explicit)
    env = os.environ.get("SHIPGUARD_TSX")
    if env:
        return Path(env)
    import shutil
    which = shutil.which("tsx")
    if which:
        return Path(which)
    here = Path(__file__).resolve()
    for parent in here.parents:
        for cand in (parent / "sentinel-verified" / "node_modules" / ".bin" / "tsx",
                     parent / "node_modules" / ".bin" / "tsx"):
            if cand.exists():
                return cand
    return None


def _changed_exports(repo: Path, changed_files: list[str], module: str) -> list[str]:
    """Exports of the changed module (the behavioural surface under investigation)."""
    mod = repo / module
    if not mod.exists() or module not in changed_files:
        return []
    from .sources import extract_signatures
    return [s.export for s in extract_signatures(mod.read_text(errors="replace"))]


def _diff_against_base(repo: Path, base: str) -> list[str]:
    """Repo-relative changed file paths between ``base`` and the working tree."""
    try:
        out = subprocess.run(["git", "-C", str(repo), "diff", "--name-only", base],
                             capture_output=True, text=True, timeout=60)
        files = [f.strip() for f in out.stdout.splitlines() if f.strip()]
        if out.returncode != 0:
            # base may not exist locally (e.g. origin/main without a fetch); try creating it
            subprocess.run(["git", "-C", str(repo), "fetch", "--quiet", "--all"], capture_output=True, timeout=120)
            out = subprocess.run(["git", "-C", str(repo), "diff", "--name-only", base],
                                 capture_output=True, text=True, timeout=60)
            files = [f.strip() for f in out.stdout.splitlines() if f.strip()]
            if out.returncode != 0:
                return []
        return files
    except Exception:  # noqa: BLE001
        return []


def _overall(findings: list[Finding], rep: ExecutionReport, executed_any: bool,
             env_failed: bool) -> str:
    if env_failed and not executed_any:
        return STATUS_ENV_FAILURE
    if not executed_any:
        return STATUS_INSUFFICIENT
    confirmed = [f for f in findings if f.bde_status == STATUS_CONFIRMED]
    regressions = [f for f in findings if f.bde_status == "REGRESSION_OBSERVED"]
    if confirmed or regressions:
        return STATUS_CONFIRMED if confirmed else "REGRESSION_OBSERVED"
    if env_failed:
        return STATUS_ENV_FAILURE
    if findings:
        return "REVIEW_REQUIRED"
    if rep.skipped or rep.not_run:
        return STATUS_INSUFFICIENT
    return STATUS_VERIFIED


def _guess_module(clone: Path) -> str | None:
    for cand in ("src/index.ts", "src/index.js", "src/main.ts", "index.ts", "index.js", "src/mod.ts"):
        if (clone / cand).exists():
            return cand
    return None


def run_bde(source_repo: Path, *, module: str | None = None, export: str | None = None,
            base: str | None = None, out_dir: Path, tsx_path: str | None = None,
            allow_local: bool = False, policy: Policy | None = None,
            work_dir: Path | None = None, include_preservation: bool | None = None,
            runner: str = "local", image: str | None = None,
            allow_host_intake: bool = False) -> BDEResult:
    """The single implementation behind ``shipguard discover`` and ``shipguard check``.

    ``base=None`` (discover): the whole module is the investigation target.
    ``base=<rev>`` (check): only behaviour related to the diff vs ``base`` is targeted, and
    preservation laws compiled from the BASE revision's own tests become the regression
    backbone executed against the candidate.
    """
    import time
    started = time.monotonic()
    source_repo = Path(source_repo).resolve()
    mode = "check" if base else "discover"
    policy = policy or Policy()
    tsx = _find_tsx(tsx_path)

    result = BDEResult(mode=mode, module=module or "")
    result.limitations = [
        "law execution runs the project's own module code in a local subprocess under the same "
        "OS user (advisory isolation, like Sentinel's local runner) — not a hostile-code sandbox",
        "deterministic offline mode: laws come from parsing and program analysis only; no LLM "
        "inference is used or required",
        "the signature extractor is a lexical scanner for common exported-function shapes; "
        "unusual syntax may be skipped (skips are reported, never guessed)",
    ]

    # Docker contains target execution, not the host's Git/configuration or collector.
    # Refuse before any Git command or target-file read unless that intake is trusted.
    if not (allow_host_intake or (runner == "local" and _consented(allow_local))):
        result.overall_status = STATUS_ENV_FAILURE
        result.notes.append("host repository intake requires explicit consent: use --allow-host-intake "
                            "only for a reviewed tree and trusted Git configuration; arbitrary hostile "
                            "repository intake is unsupported, including with Docker")
        result.not_checked.append({"reason": "host intake consent missing", "laws": 0})
        return result
    from .intake import IntakeRefused, copy_tracked_overlay, relative_parts
    try:
        if module is not None:
            relative_parts(module)
    except IntakeRefused as exc:
        result.overall_status = STATUS_ENV_FAILURE
        result.notes.append(str(exc))
        return result

    if not (source_repo / ".git").exists():
        result.notes.append("not a git repository — evidence binding requires Git history")
        result.overall_status = STATUS_ENV_FAILURE
        return result
    fingerprint_before = repo_fingerprint(source_repo)
    result.tracked_files = fingerprint_before["tracked_files"]
    result.source_sha256 = fingerprint_before["tracked_content_sha256"]

    work = Path(work_dir) if work_dir else out_dir / "tmp"
    work.mkdir(parents=True, exist_ok=True)
    clone = clone_isolated(source_repo, work)
    # A developer's candidate is often an UNCOMMITTED working tree. git clone cannot carry
    # it, so tracked-file modifications are copied into the disposable clone verbatim
    # (the original is still only read). Untracked files are counted and reported, not copied.
    dirty = subprocess.run(["git", "-C", str(source_repo), "status", "--porcelain"],
                           capture_output=True, text=True).stdout.splitlines()
    modified = [ln[3:] for ln in dirty if ln.startswith(" M") or ln.startswith("M ")]
    untracked = [ln[3:] for ln in dirty if ln.startswith("??")]
    if modified:
        try:
            for rel in modified:
                copy_tracked_overlay(source_repo, clone, rel)
        except (IntakeRefused, OSError) as exc:
            result.overall_status = STATUS_ENV_FAILURE
            result.notes.append(f"tracked overlay intake refused: {exc}")
            _finish(result, source_repo, fingerprint_before, started)
            return result
        result.notes.append(f"{len(modified)} uncommitted tracked modification(s) carried into "
                            f"the disposable clone for verification")
    if untracked:
        result.notes.append(f"{len(untracked)} untracked file(s) NOT inspected (add and commit "
                            f"them, or pass --repo at a committed state)")
    result.clone_dir = str(clone)
    result.revision = git_head(clone)

    if module is None:
        module = _guess_module(clone)
        if module is None:
            result.notes.append("no supported target module found (pass --module explicitly)")
            result.overall_status = STATUS_ENV_FAILURE
            _finish(result, source_repo, fingerprint_before, started)
            return result
    result.module = module
    if not (clone / module).exists():
        result.notes.append(f"module {module!r} does not exist in the repository")
        result.overall_status = STATUS_ENV_FAILURE
        _finish(result, source_repo, fingerprint_before, started)
        return result

    if base:
        result.changed_files = _diff_against_base(clone, base)
        if not result.changed_files:
            result.notes.append(f"no diff against {base} — nothing to check")
            result.overall_status = STATUS_VERIFIED
            result.not_checked.append({"reason": "no changes", "laws": 0})
            _finish(result, source_repo, fingerprint_before, started)
            return result
        result.changed_exports = _changed_exports(clone, result.changed_files, module)
        exports_of_interest = result.changed_exports or None
    else:
        exports_of_interest = [export] if export else None

    try:
        bundle = collect(clone, module, result.revision, exports_of_interest=exports_of_interest)
    except IntakeRefused as exc:
        result.overall_status = STATUS_ENV_FAILURE
        result.notes.append(f"repository evidence intake refused: {exc}")
        _finish(result, source_repo, fingerprint_before, started)
        return result
    if include_preservation is None:
        include_preservation = bool(base)      # check mode: preservation is the regression backbone
    laws = compile_laws(bundle, exports_of_interest=exports_of_interest,
                        include_preservation=include_preservation)
    annotate_section_arity(laws, bundle)
    report = qualify(laws, policy)
    result.laws_total = len(laws)
    result.laws_blocking = len(report.blocking)
    result.laws_hypotheses = len(report.hypotheses)
    result.laws_preservation = len(report.preservation)

    if not laws:
        result.overall_status = STATUS_INSUFFICIENT
        result.not_checked.append({"reason": "no laws could be compiled from the permitted evidence",
                                   "laws": 0})
        result.notes.append("the engine does not claim correctness — it found nothing it could check")
        _finish(result, source_repo, fingerprint_before, started)
        return result

    if runner == "local" and not _consented(allow_local):
        result.not_run = len(laws)
        result.overall_status = STATUS_INSUFFICIENT
        result.not_checked.append({"reason": "law execution requires explicit local-execution consent "
                                             "(--allow-local or SHIPGUARD_ALLOW_LOCAL=1)",
                                   "laws": len(laws)})
        result.notes.append(f"compiled {len(laws)} candidate laws "
                            f"({len(report.blocking)} blocking-grade) — not executed without consent")
        _finish(result, source_repo, fingerprint_before, started)
        return result

    if runner == "local" and (tsx is None or not tsx.exists()):
        result.overall_status = STATUS_ENV_FAILURE
        result.not_run = len(laws)
        result.notes.append("tsx not found — set SHIPGUARD_TSX or install tsx (see shipguard doctor)")
        _finish(result, source_repo, fingerprint_before, started)
        return result

    pack, problems = build_lawpack(laws, module, result.revision, clone)
    if pack is None:
        result.overall_status = STATUS_INSUFFICIENT
        result.not_checked.append({"reason": "lawpack failed validation", "problems": problems[:5]})
        _finish(result, source_repo, fingerprint_before, started)
        return result
    if problems:
        result.notes.extend(problems[:5])
        result.not_run = len(laws) - len(pack["laws"])
        result.not_checked.append({"reason": "unexecutable or invalid law grounding", "problems": problems})

    meta = {lw.law_id: lw for lw in laws}
    rep = run_lawpack(pack, clone, tsx, laws_meta=meta, mode=mode, per_law_ms=12000, timeout_s=1200,
                      runner=runner, image=image)
    result.execution_boundary, result.runtime_image = rep.execution_boundary, rep.runtime_image
    if runner == "docker":
        result.limitations[0] = "target code ran in a constrained Docker container; the host and container runtime remain trusted"
    rep.not_run += result.not_run
    result.not_run = rep.not_run
    result.outcomes = rep.outcomes
    result.executed, result.passed = rep.executed, rep.passed
    result.failed, result.errors, result.skipped = rep.failed, rep.errors, rep.skipped
    module_sha = bundle.module_sha256
    pkg = bundle.package
    for f in rep.findings:
        result.findings.append(Finding.from_execution(f, module, result.revision, pkg, module_sha))
    result.overall_status = _overall(result.findings, rep, executed_any=rep.executed > 0,
                                     env_failed=bool(rep.runner_error or rep.errors))
    if rep.runner_error:
        result.notes.append(f"runner: {rep.runner_error}")
    result.not_checked.append({"reason": "hypothesis-grade laws are executed but never blocking",
                               "laws": result.laws_hypotheses})
    if result.errors:
        result.notes.extend(f"law {o.law_id}: {o.detail}" for o in result.outcomes if o.status == "ERROR")
        result.not_checked.append({"reason": f"{result.errors} laws errored (environment) "
                                             "and are excluded from the verdict", "laws": result.errors})
    _finish(result, source_repo, fingerprint_before, started, evidence=True, out_dir=out_dir,
            clone=clone, laws=laws, report=report, bundle=bundle)
    return result


def _guess_module(clone: Path) -> str | None:
    for cand in ("src/index.ts", "src/index.js", "src/main.ts", "index.ts", "index.js", "src/mod.ts"):
        if (clone / cand).exists():
            return cand
    return None


def _finish(result: BDEResult, source_repo: Path, before: dict[str, Any], started: float,
            *, evidence: bool = False, out_dir: Path | None = None, clone: Path | None = None,
            laws: list[BehaviouralLaw] | None = None, report: AuthorityReport | None = None,
            bundle: EvidenceBundle | None = None) -> None:
    after = repo_fingerprint(source_repo)
    result.original_untouched = (after == before)
    result.duration_ms = int((time.monotonic() - started) * 1000)
    if evidence and out_dir is not None:
        import hashlib
        out_dir.mkdir(parents=True, exist_ok=True)
        result.evidence_dir = str(out_dir)
        (out_dir / "bde-laws.json").write_text(json.dumps(
            {"schema_version": 1, "module": result.module, "git_revision": result.revision,
             "laws": [lw.to_dict() for lw in (laws or [])]}, indent=2, ensure_ascii=False, default=str))
        result.lawpack_sha256 = hashlib.sha256((out_dir / "bde-laws.json").read_bytes()).hexdigest()
        write_evidence(out_dir, result)
    if clone is not None:
        # the disposable clone is kept under the gitignored work dir for `shipguard reproduce`
        pass

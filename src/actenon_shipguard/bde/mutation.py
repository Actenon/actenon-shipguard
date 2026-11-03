"""Controlled mutation-sensitivity probes (mandate §6.5, benchmark Track B).

Creates isolated, single-token semantic mutations of a KNOWN-VALID implementation in a
DISPOSABLE COPY and measures whether the compiled behavioural laws detect them. The
developer's repository is never touched; mutations never leave their copy.

Honest semantics: a surviving mutation is evidence of LIMITED DETECTION SENSITIVITY for the
compiled law set — never proof that the original source contains a defect. Mutations that
break syntax are reported as neutral (the module no longer imports), not as detections.

The mutation operators are deliberately tiny, reviewable token substitutions applied ONE
occurrence at a time (the first K occurrences of each operator), so a detection means the
law noticed a genuine behavioural change, not a syntax catastrophe.
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .laws import BehaviouralLaw
from .scheduler import build_lawpack, run_lawpack

# (mutation_id, description, [(old_token, new_token)], max_occurrences)
OPERATORS: list[tuple[str, str, tuple[str, str], int]] = [
    ("eq-flip",     "flip the first '===' to '!=='", ("===", "!=="), 1),
    ("neq-flip",    "flip the first '!==' to '==='", ("!==", "==="), 1),
    ("and-or-flip", "flip the first '&&' to '||'", ("&&", "||"), 1),
    ("or-and-flip", "flip the first '||' to '&&'", ("||", "&&"), 1),
    ("true-flip",   "flip the first 'true' literal to 'false'", ("true", "false"), 1),
    ("false-flip",  "flip the first 'false' literal to 'true'", ("false", "true"), 1),
    ("not-drop",    "drop the first '!' logical negation", ("!(", "("), 1),
    ("return-void", "blank the first 'return ' statement value", ("return ", "return undefined; //"), 1),
]

# Harmless refactor controls: transformations that are PROVABLY behaviour-preserving.
# (A declaration rename without renaming its references is NOT harmless — it breaks the
# module — so it is deliberately not used as a control.)
REFACTOR_CONTROLS: list[tuple[str, str, tuple[str, str]]] = [
    ("comment",   "append a source comment", ("", "\n// refactored: harmless comment\n")),
    ("blankline", "insert a blank line before the first export", ("export ", "\nexport ")),
]


@dataclass
class MutationResult:
    mutation_id: str
    description: str
    applied: bool = False          # the token substitution found a site
    importable: bool = False       # the mutated module still imports
    detected: bool = False         # a law that passed on clean code now fails
    surviving: bool = False
    neutral: bool = False          # not applied / not importable / no comparable laws
    findings: list[dict[str, Any]] = field(default_factory=list)
    detail: str = ""


def _apply_token_mutation(text: str, old: str, new: str, occurrence: int) -> tuple[str, bool]:
    idx = -1
    for _ in range(occurrence + 1):
        idx = text.find(old, idx + 1)
        if idx < 0:
            return text, False
    return text[:idx] + new + text[idx + len(old):], True


def _copy_repo(src: Path, work: Path, tag: str) -> Path:
    dest = work / f"mut-{tag}"
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src, dest, symlinks=True, ignore=shutil.ignore_patterns("node_modules"))
    # share node_modules by symlink for module resolution
    nm = src / "node_modules"
    if nm.exists():
        (dest / "node_modules").symlink_to(nm, target_is_directory=True)
    return dest


def probe_mutations(source_repo: Path, module: str, laws: list[BehaviouralLaw], tsx: Path,
                    *, work: Path, mode: str = "discover",
                    operators: list[tuple[str, str, tuple[str, str], int]] | None = None,
                    refactors: list[tuple[str, str, tuple[str, str]]] | None = None) -> dict[str, Any]:
    """Run every mutation operator against the SAME compiled law set, in disposable copies.

    ``source_repo`` must already be a disposable clone (never the developer's original).
    """
    work.mkdir(parents=True, exist_ok=True)
    module_path = source_repo / module
    original_text = module_path.read_text()

    # clean baseline for this law set
    pack, problems = build_lawpack(laws, module, "mutation-probe", source_repo)
    if pack is None:
        return {"error": "lawpack failed validation", "problems": problems[:5]}
    meta = {lw.law_id: lw for lw in laws}
    clean = run_lawpack(pack, source_repo, tsx, laws_meta=meta, mode=mode)
    clean_failed = {o.law_id for o in clean.outcomes if o.status == "FAIL"}

    results: list[MutationResult] = []
    for op_id, desc, (old, new), occ in (operators or OPERATORS):
        mutated, applied = _apply_token_mutation(original_text, old, new, occ - 1)
        r = MutationResult(mutation_id=op_id, description=desc, applied=applied)
        if not applied:
            r.neutral = True
            r.detail = f"token {old!r} not found"
            results.append(r)
            continue
        repo = _copy_repo(source_repo, work, op_id)
        (repo / module).write_text(mutated)
        rep = run_lawpack(pack, repo, tsx, laws_meta=meta, mode=mode)
        failed = [o for o in rep.outcomes if o.status == "FAIL" and o.law_id not in clean_failed]
        errored = [o for o in rep.outcomes if o.status == "ERROR" and o.law_id not in
                   {c.law_id for c in clean.outcomes if c.status == "ERROR"}]
        if errored and not failed:
            r.importable = False
            r.neutral = True
            r.detail = f"module no longer imports after mutation ({errored[0].detail or 'error'})"
        elif failed:
            r.importable = True
            r.detected = True
            r.findings = [dict(f) for f in rep.findings if (f.get("law") or {}).get("law_id")
                          not in clean_failed]
        else:
            r.importable = True
            r.surviving = True
            r.detail = "no compiled law noticed the behavioural change"
        results.append(r)

    refactor_results: list[MutationResult] = []
    for op_id, desc, (old, new) in (refactors or REFACTOR_CONTROLS):
        text2 = original_text + new if not old else original_text.replace(old, new, 1)
        applied = bool(new) and (not old or old in original_text)
        r = MutationResult(mutation_id=f"refactor:{op_id}", description=desc, applied=applied)
        if not applied:
            r.neutral = True
            r.detail = "transformation not applicable"
            refactor_results.append(r)
            continue
        repo = _copy_repo(source_repo, work, f"refactor-{op_id}")
        (repo / module).write_text(text2)
        rep = run_lawpack(pack, repo, tsx, laws_meta=meta, mode=mode)
        failed = [o for o in rep.outcomes if o.status == "FAIL" and o.law_id not in clean_failed]
        if failed:
            r.detected = True         # a FALSE POSITIVE on a harmless refactor
            r.findings = [dict(f) for f in rep.findings if (f.get("law") or {}).get("law_id")
                          not in clean_failed]
        else:
            r.surviving = True
        refactor_results.append(r)

    behavioural = [r for r in results if r.applied and r.importable]
    return {
        "clean_baseline": {"executed": clean.executed, "passed": clean.passed,
                           "failed": clean.failed},
        "mutations": [r.__dict__ for r in results],
        "refactor_controls": [r.__dict__ for r in refactor_results],
        "summary": {
            "behavioural_mutations": len(behavioural),
            "detected": sum(1 for r in behavioural if r.detected),
            "surviving": sum(1 for r in behavioural if r.surviving),
            "neutral": sum(1 for r in results if r.neutral),
            "detection_rate": (round(sum(1 for r in behavioural if r.detected) / len(behavioural), 3)
                               if behavioural else None),
            "refactor_false_positives": sum(1 for r in refactor_results if r.detected),
        },
    }

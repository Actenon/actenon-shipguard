"""Counterexamples as first-class artifacts (mandate §10).

A finding is not a comment — it is a self-describing, independently reproducible record:
law identity + provenance + approval status, exact revision and dependency identity,
minimal input, expected vs observed behaviour, a reproduction command, the runner, hashes,
confidence and limitations, and suggested repair context.

The evidence manifest is PORTABLE: relative paths only, no absolute machine paths, no
private data. A standalone ``reproduce.mjs`` is emitted next to the manifest so any
developer with Node+tsx can re-execute the witness without ShipGuard.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .laws import BehaviouralLaw
from .scheduler import (STATUS_CONFIRMED, STATUS_HYPOTHESIS, STATUS_REGRESSION, STATUS_REVIEW,
                        LawOutcome)

FINDING_SCHEMA_VERSION = 1


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _short(v: Any, n: int = 60) -> str:
    s = json.dumps(v, ensure_ascii=False, default=str) if not isinstance(v, str) else v
    s = s if len(s) <= n else s[: n - 1] + "…"
    return s


@dataclass
class Finding:
    finding_id: str
    bde_status: str                       # CONFIRMED_CONTRADICTION | REGRESSION_OBSERVED | HYPOTHESIS_FALSIFIED | REVIEW_REQUIRED
    law: dict[str, Any]                   # the law subset carried from the scheduler
    module: str
    export: str
    minimal_args: list[Any]
    original_args: list[Any] | None
    kind: str | None
    detail: str | None
    expected: Any = None
    observed: Any = None
    shrunk: bool | None = None
    boundary_index: int | None = None
    reproduction: dict[str, Any] = field(default_factory=dict)
    dependency_identity: dict[str, Any] = field(default_factory=dict)
    repair_context: dict[str, Any] = field(default_factory=dict)
    discovered_at: str = field(default_factory=_now)
    schema_version: int = FINDING_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_execution(f: dict[str, Any], module: str, revision: str,
                       package: dict[str, Any], module_sha: str) -> "Finding":
        law = f.get("law") or {}
        fid = f"bde-{uuid.uuid4().hex[:10]}"
        args = f.get("args") if isinstance(f.get("args"), list) else (f.get("original_args") or [])
        dep = {"package": package.get("name"), "package_version": package.get("version"),
               "module": module, "module_sha256": module_sha, "git_revision": revision,
               "law_digest_source": (law.get("grounding") or {}).get("sha256")}
        repair = {
            "target_file": module,
            "export": law.get("export"),
            "law_statement": law.get("statement"),
            "grounding": {k: (law.get("grounding") or {}).get(k)
                          for k in ("file", "line_start", "line_end", "excerpt", "source_type")},
            "hint": (f"Violated law grounded in {(law.get('grounding') or {}).get('file')}:"
                     f"{(law.get('grounding') or {}).get('line_start')}. Minimal failing input: "
                     f"{law.get('export')}({_short(args)}). {f.get('detail') or ''}")[:600],
        }
        return Finding(
            finding_id=fid, bde_status=f.get("bde_status", STATUS_REVIEW), law=law,
            module=module, export=str(law.get("export", "")),
            minimal_args=args, original_args=f.get("original_args"),
            kind=f.get("kind"), detail=f.get("detail"),
            expected=f.get("expected"), observed=f.get("observed"),
            shrunk=f.get("shrunk"), boundary_index=f.get("boundary_index"),
            dependency_identity=dep, repair_context=repair)


def reproduce_script(finding: Finding, module: str) -> str:
    """A standalone, dependency-light reproduction script for one finding.

    Runs the exact witness arguments against the target module and prints expected/observed.
    Anyone with node+tsx can run it — no ShipGuard installation required.
    """
    args_json = json.dumps(finding.minimal_args, ensure_ascii=False)
    expected_json = json.dumps(finding.expected, ensure_ascii=False, default=str)
    law_stmt = (finding.law.get("statement") or "").replace("`", "'").replace("${", "$ {")
    return f"""// Actenon ShipGuard BDE — standalone reproduction of finding {finding.finding_id}
// Law: {law_stmt}
// Status: {finding.bde_status}
// Grounding: {(finding.law.get('grounding') or {}).get('file')}:{(finding.law.get('grounding') or {}).get('line_start')}
// Run from the repository root:  tsx <this-file>.mjs
import {{ pathToFileURL }} from 'node:url';
import {{ resolve }} from 'node:path';
const MODULE = {json.dumps(module)};
const ARGS = {args_json};
const EXPECTED = {expected_json};
const mod = await import(pathToFileURL(resolve(MODULE)).href);
const fn = mod[{json.dumps(finding.export)}];
if (typeof fn !== 'function') {{ console.error('export not found'); process.exit(2); }}
let outcome;
try {{ outcome = {{ threw: false, returned: fn(...ARGS) }}; }}
catch (e) {{ outcome = {{ threw: true, name: e?.constructor?.name, message: String(e?.message ?? e) }}; }}
const show = (v) => {{ try {{ const s = JSON.stringify(v); return s === undefined ? String(v) : s; }} catch {{ return String(v); }} }};
console.log('finding   : {finding.finding_id}');
console.log('law       : {law_stmt[:160]}');
console.log('input     : ' + show(ARGS));
console.log('expected  : ' + show(EXPECTED));
console.log('observed  : ' + (outcome.threw ? `threw ${{outcome.name}}: ${{outcome.message}}` : show(outcome.returned)));
console.log('verdict   : ' + (outcome.threw ? 'VIOLATION (documented call threw)' : 'see expected vs observed'));
"""


def write_evidence(out_dir: Path, result: "BDEResult") -> Path:   # noqa: F821
    """Write the portable evidence manifest + per-finding reproduction scripts."""
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema": "actenon-shipguard/bde/evidence/1",
        "generated_at": _now(),
        "mode": result.mode,
        "repo": {"tracked_files": result.tracked_files, "git_head": result.revision,
                 "original_untouched": result.original_untouched},
        "module": result.module,
        "summary": {
            "laws_discovered": result.laws_total,
            "laws_blocking": result.laws_blocking,
            "laws_executed": result.executed,
            "laws_passed": result.passed, "laws_failed": result.failed,
            "laws_errored": result.errors, "laws_skipped": result.skipped,
            "overall_status": result.overall_status,
        },
        "findings": [f.to_dict() for f in result.findings],
        "checked_and_passed": [
            {"law_id": o.law_id, "predicate": o.predicate, "trials": o.trials}
            for o in result.outcomes if o.status == "PASS"],
        "not_checked": result.not_checked,
        "limitations": result.limitations,
        "reproduction": {
            "shipguard": f"shipguard reproduce <finding-id> --evidence {out_dir.name}",
            "standalone": [f"bde-repro-{f.finding_id}.mjs" for f in result.findings],
        },
    }
    mp = out_dir / "bde-evidence.json"
    mp.write_text(json.dumps(manifest, indent=2, ensure_ascii=False, default=str) + "\n")
    digest = hashlib.sha256(mp.read_bytes()).hexdigest()
    (out_dir / "bde-evidence.sha256").write_text(digest + "\n")
    for f in result.findings:
        (out_dir / f"bde-repro-{f.finding_id}.mjs").write_text(reproduce_script(f, result.module))
    return mp

"""BDE research benchmark (mandate §12): frozen corpus, blind discovery, held-out scoring.

TRACK A — natural developer defects. The six frozen v0.2.0 corpus tasks (3 real projects)
are re-used as TARGETS ONLY: BDE receives the buggy baseline repository and its permitted
evidence (source, signatures, docs, its own tests) — it is never given the v0.2.0 manifest's
requirements, contracts, prompts or expected outcomes. The upstream fix commit is HELD OUT
and used exclusively by the SCORER to classify each finding:

  * DISCOVERED_DEFECT  — a law fails at the baseline AND passes at the upstream fix
                         (the witness is a genuine reproduction of the historical defect).
  * TRUE_DOC_DRIFT     — fails at both revisions; the documented example verifiably does not
                         match the code (audited manually; audit commands in the report).
  * TRUE_DELAYED_FIX   — fails at both revisions; upstream later changed exactly this
                         behaviour (audited against a later commit).
  * FALSE_POSITIVE     — fails at both revisions with no audit support (an invalid law).
  * MISS               — no target-defect finding for the task.

TRACK B — mutation sensitivity and false positives on KNOWN-VALID implementations (the fix
revisions): controlled single-token mutations in disposable copies, plus harmless-refactor
controls that must not trigger findings.

The corpus and rubric are frozen in manifest.json BEFORE the formal run; results are written
exactly as measured, including misses, abstentions and false positives.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "benchmark"))
sys.path.insert(0, str(REPO_ROOT / "src"))

from harness import materialize, task_module, task_export            # noqa: E402  (v0.2.0 corpus harness)
from actenon_shipguard.bde.authority import Policy, annotate_section_arity, qualify   # noqa: E402
from actenon_shipguard.bde.compiler import compile_laws              # noqa: E402
from actenon_shipguard.bde.mutation import probe_mutations           # noqa: E402
from actenon_shipguard.bde.scheduler import build_lawpack, run_lawpack  # noqa: E402
from actenon_shipguard.bde.sources import collect                    # noqa: E402

HERE = Path(__file__).resolve().parent
V020_MANIFEST = REPO_ROOT / "BENCHMARK-MANIFEST-v0.2.0.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _tsx() -> Path:
    import os
    env = os.environ.get("SHIPGUARD_TSX")
    if env:
        return Path(env)
    for cand in (REPO_ROOT.parent / "sentinel-verified" / "node_modules" / ".bin" / "tsx",
                 Path("/tmp/sentinel-verified/node_modules/.bin/tsx")):
        if cand.exists():
            return cand
    raise SystemExit("tsx not found (SHIPGUARD_TSX)")


def _discover(repo: Path, module: str, revision: str, tsx: Path):
    """BLIND discovery on one repository: only repo evidence in, laws + findings out."""
    bundle = collect(repo, module, revision)
    laws = compile_laws(bundle, include_preservation=False)
    annotate_section_arity(laws, bundle)
    report = qualify(laws, Policy())
    pack, problems = build_lawpack(laws, module, revision, repo)
    meta = {l.law_id: l for l in laws}
    execution = run_lawpack(pack, repo, tsx, laws_meta=meta, mode="discover") if pack else None
    return {"bundle": bundle, "laws": laws, "authority": report, "pack": pack,
            "problems": problems, "execution": execution}


def _witness_status_at(law_obj, witness_args: list, repo: Path, module: str, tsx: Path) -> str:
    """Re-execute ONE law restricted to ONE specific witness input at another revision.

    This is WITNESS-level scoring: the question is whether the engine's reported minimal
    input still violates the law after the upstream fix — i.e. whether the witness
    reproduces the historical defect — independent of what the law's full domain does.
    """
    from actenon_shipguard.bde.strategies import execution_for
    entry = execution_for(law_obj)
    if entry is None:
        return "ERROR"
    gen = dict(entry.get("gen") or {})
    gen.update({"mode": "literal", "args": witness_args, "shrink": False})
    entry = {**entry, "gen": gen}
    pack = {"schema_version": 1, "module": module, "git_revision": "", "laws": [entry]}
    rep = run_lawpack(pack, repo, tsx, laws_meta={law_obj.law_id: law_obj}, mode="discover")
    o = rep.outcomes_for(law_obj.law_id)
    return o.status if o else "ERROR"


def _finding_signature(f: dict[str, Any]) -> str:
    """Robust behavioural-family signature (export:kind) — stable across README/JSDoc copies
    of the same documented example and across revision line shifts."""
    law = f.get("law") or {}
    return f"{law.get('export')}:{f.get('kind')}"


def run_track_a(work: Path, tsx: Path, v020: dict[str, Any], audit: dict[str, str]) -> dict[str, Any]:
    tasks = v020["tasks"]
    out: dict[str, Any] = {"track": "A", "tasks": []}
    for t in tasks:
        tid, mod = t["id"], task_module(t)
        base_repo = materialize(t, work, at="baseline")
        fix_repo = materialize(t, work, at="fix")
        rev = f"{t['fix_commit']}^"
        d = _discover(base_repo, mod, rev, tsx)
        ex = d["execution"]
        task_rec: dict[str, Any] = {
            "task": tid, "project": t["project"], "module": mod, "fix_commit": t["fix_commit"],
            "laws_discovered": len(d["laws"]),
            "laws_blocking": len(d["authority"].blocking),
            "laws_executed": ex.executed if ex else 0,
            "laws_passed": ex.passed if ex else 0,
            "findings": [], "verdict": "MISS", "notes": [],
        }
        for f in (ex.findings if ex else []):
            law = f.get("law") or {}
            full_law = next((l for l in d["laws"] if l.law_id == law.get("law_id")), None)
            witness = f.get("args") if isinstance(f.get("args"), list) else (f.get("original_args") or [])
            status_at_fix = _witness_status_at(full_law, witness, fix_repo, mod, tsx) if full_law else "ERROR"
            sig = _finding_signature(f)
            label = "FALSE_POSITIVE"
            if status_at_fix == "PASS":
                label = "DISCOVERED_DEFECT"
            elif sig in audit:
                label = audit[sig]
            finding_rec = {
                "finding": sig, "bde_status": f.get("bde_status"),
                "statement": (law.get("statement") or "")[:140],
                "grounding": {k: (law.get("grounding") or {}).get(k)
                              for k in ("file", "line_start", "source_type")},
                "witness": witness, "detail": (f.get("detail") or "")[:220],
                "witness_status_at_fix_revision": status_at_fix, "label": label,
            }
            task_rec["findings"].append(finding_rec)
        if any(x["label"] == "DISCOVERED_DEFECT" for x in task_rec["findings"]):
            task_rec["verdict"] = "DISCOVERED"
        elif any(x["label"].startswith("TRUE_") for x in task_rec["findings"]):
            task_rec["verdict"] = "MISS_WITH_TRUE_AUXILIARY_FINDINGS"
        # positive control: discovery at the fix revision must stay clean of UNLABELLED findings
        df = _discover(fix_repo, mod, t["fix_commit"], tsx)
        exf = df["execution"]
        fix_fps = []
        for f in (exf.findings if exf else []):
            sig = _finding_signature(f)
            if sig not in audit:
                fix_fps.append(sig)
        task_rec["positive_control_unlabelled_findings_at_fix"] = fix_fps
        task_rec["laws_at_fix"] = len(df["laws"])
        out["tasks"].append(task_rec)
        print(f"  [A] {tid:46s} -> {task_rec['verdict']}", flush=True)
    out["summary"] = {
        "tasks": len(out["tasks"]),
        "discovered": sum(1 for x in out["tasks"] if x["verdict"] == "DISCOVERED"),
        "missed": sum(1 for x in out["tasks"] if x["verdict"].startswith("MISS")),
        "false_positive_findings": sum(1 for x in out["tasks"] for y in x["findings"]
                                       if y["label"] == "FALSE_POSITIVE"),
        "true_doc_drift_findings": sum(1 for x in out["tasks"] for y in x["findings"]
                                       if y["label"] == "TRUE_DOC_DRIFT"),
        "true_delayed_fix_findings": sum(1 for x in out["tasks"] for y in x["findings"]
                                         if y["label"] == "TRUE_DELAYED_FIX"),
        "positive_control_violations": sum(len(x["positive_control_unlabelled_findings_at_fix"])
                                           for x in out["tasks"]),
    }
    return out


def run_track_b(work: Path, tsx: Path, v020: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {"track": "B", "projects": []}
    for t in v020["tasks"]:
        fix_repo = materialize(t, work, at="fix")
        mod = task_module(t)
        d = _discover(fix_repo, mod, t["fix_commit"], tsx)
        if not d["laws"] or d["execution"] is None:
            continue
        res = probe_mutations(fix_repo, mod, d["laws"], tsx, work=work / f"mut-{t['id']}")
        res["task"] = t["id"]
        res["laws"] = len(d["laws"])
        out["projects"].append(res)
        s = res.get("summary") or {}
        print(f"  [B] {t['id']:46s} -> detected {s.get('detected')}/{s.get('behavioural_mutations')} "
              f"mutations, refactor FPs {s.get('refactor_false_positives')}", flush=True)
    ds = [p["summary"]["detected"] for p in out["projects"] if p.get("summary")]
    bm = [p["summary"]["behavioural_mutations"] for p in out["projects"] if p.get("summary")]
    out["summary"] = {
        "projects": len(out["projects"]),
        "behavioural_mutations": sum(bm),
        "detected": sum(ds),
        "detection_rate": round(sum(ds) / sum(bm), 3) if sum(bm) else None,
        "refactor_false_positives": sum(p["summary"]["refactor_false_positives"] for p in out["projects"]),
    }
    return out


def freeze(engine_commit: str) -> dict[str, Any]:
    v020 = json.loads(V020_MANIFEST.read_text())
    manifest = {
        "schema": "actenon-shipguard/bde/benchmark-manifest/1",
        "frozen_at": _now(),
        "engine": {"commit": engine_commit,
                   "law_catalogue": "intent-compiler/1 + runner predicates v1",
                   "policy": "default (Q1 doc-example and Q2 splitter-boundary promotions enabled)"},
        "purpose": ("Measure, honestly, whether BDE can discover real historical defects from "
                    "permitted repository evidence alone (no hand-authored acceptance contracts), "
                    "and quantify mutation sensitivity and false positives on known-valid code."),
        "track_a": {
            "corpus": "the frozen v0.2.0 corpus TARGETS ONLY (project, module, fix_commit); the "
                      "v0.2.0 requirements/contracts/prompts are NOT inputs to BDE at any point",
            "scoring_rubric": {
                "DISCOVERED_DEFECT": "law fails at baseline AND passes at the upstream fix "
                                     "(witness reproduces the historical defect)",
                "TRUE_DOC_DRIFT": "fails at both revisions; documented example verifiably "
                                  "contradicts the code (audited; commands in report)",
                "TRUE_DELAYED_FIX": "fails at both revisions; upstream later changed exactly "
                                    "this behaviour (audited against a later commit)",
                "FALSE_POSITIVE": "fails at both revisions with no audit support",
                "MISS": "no target-defect finding",
            },
            "audit_labels": {
                # robust export:kind keys — the same documented example appears in the README and
                # in generated JSDoc copies (automd); line numbers shift between revisions, so
                # labels match on the behavioural family, not on positions
                "isScriptProtocol:documented_result_mismatch": "TRUE_DOC_DRIFT",
                "normalizeURL:documented_result_mismatch": "TRUE_DOC_DRIFT",
                "withFragment:documented_result_mismatch": "TRUE_DOC_DRIFT",
                # 9927800 splitByCase splits at caseless characters; upstream 57cfd15
                # ("assume characters lowercase by default") changed exactly this behaviour
                "splitByCase:unjustified_boundary": "TRUE_DELAYED_FIX",
            },
            "audit_evidence": {
                "isScriptProtocol": "tsx -e 'import {isScriptProtocol} from "./src/index.ts"; "
                                     "console.log(isScriptProtocol("javascript:alert(1)"))' -> false, "
                                     "while README/JSDoc document `// true`",
                "normalizeURL": "README documents 'test?query=123%20123#hash,%20test'; the code returns "
                                "'test?query=123+123#hash,%20test' (space -> + vs %20)",
                "withFragment": "README documents withFragment('/foo#bar', '') -> '/foo'; the code "
                                "returns '/foo#bar' (empty hash does not remove the fragment)",
                "splitByCase": "at 9927800 splitByCase('a-', []) -> ['a','-']; at 57cfd15 the same "
                               "call -> ['a-'] (upstream changed caseless-char handling)",
            },
        },
        "track_b": {
            "subjects": "the six fix revisions (known-valid) + harmless-refactor controls",
            "operators": ["eq-flip", "neq-flip", "and-or-flip", "or-and-flip", "true-flip",
                          "false-flip", "not-drop", "return-void"],
            "semantics": "a surviving mutation is limited detection sensitivity, never a "
                         "defect claim; refactor controls must produce zero findings",
        },
        "no_post_hoc_changes": "the corpus, rubric and audit labels are frozen before the formal "
                               "run; results are published as measured",
    }
    (HERE / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--freeze-only", action="store_true")
    ap.add_argument("--work", default="/tmp/sg-bde-bench")
    args = ap.parse_args()
    engine_commit = subprocess.run(["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"],
                                   capture_output=True, text=True).stdout.strip()
    manifest = json.loads((HERE / "manifest.json").read_text()) if (HERE / "manifest.json").exists() \
        else freeze(engine_commit)
    if args.freeze_only:
        print(json.dumps(manifest, indent=2))
        return 0
    started = time.monotonic()
    v020 = json.loads(V020_MANIFEST.read_text())
    work = Path(args.work)
    work.mkdir(parents=True, exist_ok=True)
    tsx = _tsx()
    audit = manifest["track_a"]["audit_labels"]
    print("TRACK A — natural developer defects (blind discovery, held-out scoring)")
    track_a = run_track_a(work, tsx, v020, audit)
    print("TRACK B — mutation sensitivity + false positives on known-valid revisions")
    track_b = run_track_b(work, tsx, v020)
    results = {
        "schema": "actenon-shipguard/bde/benchmark-results/1",
        "generated_at": _now(), "engine_commit": engine_commit,
        "duration_s": round(time.monotonic() - started, 1),
        "track_a": track_a, "track_b": track_b,
    }
    (HERE / "results.json").write_text(json.dumps(results, indent=2, ensure_ascii=False, default=str) + "\n")
    print(json.dumps({"A": track_a["summary"], "B": track_b["summary"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

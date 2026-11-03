"""Developer-facing BDE results: terminal summary, JSON, self-contained HTML.

The primary output is understandable in seconds (mandate §9): what changed, how many laws
were discovered/approved/executed, each contradiction with its minimal witness and
provenance, and — when nothing was found — exactly what was checked, what was not, and
what remains unknown. The engine never says "the software is correct".
"""
from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

from .check import BDEResult
from .scheduler import STATUS_CONFIRMED, STATUS_VERIFIED


def _esc(s: Any) -> str:
    return html.escape(str(s if s is not None else ""))


def terminal_summary(result: BDEResult) -> str:
    """The primary developer output. Fits the §9 target shape."""
    L: list[str] = []
    ap = L.append
    ap("ACTENON SHIPGUARD — BEHAVIOURAL DISCOVERY")
    ap(f"Mode      : {'check' if result.mode == 'check' else 'discover'}"
       f"{' (base diff)' if result.changed_files else ''}")
    ap(f"Module    : {result.module}")
    if result.changed_files:
        ap(f"Change    : {', '.join(result.changed_files[:4])}{' …' if len(result.changed_files) > 4 else ''}")
    ap(f"Revision  : {str(result.revision)[:12]}   tracked files: {result.tracked_files}")
    ap(f"Laws      : {result.laws_total} discovered · {result.laws_blocking} blocking-grade · "
       f"{result.laws_hypotheses} hypotheses (review) · {result.laws_preservation} preservation")
    if result.executed:
        ap(f"Executed  : {result.executed} laws — {result.passed} passed · {result.failed} violated · "
           f"{result.errors} errored · {result.skipped} out-of-scope  ({result.duration_ms} ms)")
    else:
        ap("Executed  : 0 laws — see notes")
    ap("")
    if result.findings:
        for f in result.findings:
            ap(f"[{f.bde_status}]  {f.finding_id}")
            g = (f.law.get("grounding") or {})
            ap(f"  Law      : {_first_line(f.law.get('statement'))}")
            ap(f"  Grounding: {g.get('file')}:{g.get('line_start')} ({g.get('source_type')})")
            ap(f"  Export   : {f.export}   Input: {_short(f.minimal_args)}")
            if f.expected is not None or f.kind in ("documented_result_mismatch", "baseline_pair_mismatch"):
                ap(f"  Expected : {_short(f.expected)}")
            ap(f"  Observed : {_short(f.observed) if f.observed is not None else _short(f.detail)}")
            ap(f"  Evidence : {f.detail}")
            ap(f"  Repro    : shipguard reproduce {f.finding_id}"
               f"   (or: tsx bde-repro-{f.finding_id}.mjs in the evidence dir)")
            ap("")
    if result.overall_status == STATUS_VERIFIED:
        ap("VERIFIED_WITHIN_SCOPE — every executed blocking/preservation law held.")
        ap("This is NOT a claim of correctness. What was NOT checked:")
        for nc in result.not_checked[:4]:
            ap(f"  - {nc.get('reason')} ({nc.get('laws', '?')} laws)")
        for note in result.limitations[:2]:
            ap(f"  - {note}")
    elif result.overall_status == "REGRESSION_OBSERVED":
        ap("REGRESSION_OBSERVED — approved preservation behaviour changed.")
    elif result.overall_status == STATUS_CONFIRMED:
        ap(f"CONFIRMED_CONTRADICTION — {sum(1 for f in result.findings if f.bde_status == STATUS_CONFIRMED)} "
           f"grounded law(s) violated with reproducible witnesses. Recommendation: BLOCK this change.")
    elif result.overall_status == "INSUFFICIENT":
        ap("INSUFFICIENT_EVIDENCE — the available evidence does not establish correctness.")
        for note in result.notes[:3]:
            ap(f"  - {note}")
    else:
        ap(f"{result.overall_status}")
        for note in result.notes[:3]:
            ap(f"  - {note}")
    if result.original_untouched is not None:
        ap(f"Source repo untouched: {result.original_untouched} (tracked-content fingerprint equal before/after)")
    if result.evidence_dir:
        ap(f"Evidence  : {result.evidence_dir}")
    return "\n".join(L)


def _first_line(s: str | None, n: int = 96) -> str:
    s = (s or "").split("\n")[0]
    return s if len(s) <= n else s[: n - 1] + "…"


def _short(v: Any, n: int = 72) -> str:
    if v is None:
        return "—"
    s = json.dumps(v, ensure_ascii=False, default=str) if not isinstance(v, str) else v
    return s if len(s) <= n else s[: n - 1] + "…"


def html_report(result: BDEResult) -> str:
    """Self-contained HTML evidence report (no external assets)."""
    rows = []
    for f in result.findings:
        g = (f.law.get("grounding") or {})
        rows.append(f"""
        <tr class="{'confirmed' if f.bde_status == STATUS_CONFIRMED else 'hypothesis'}">
          <td><code>{_esc(f.finding_id)}</code><div class="status">{_esc(f.bde_status)}</div></td>
          <td>{_esc(_first_line(f.law.get('statement'), 160))}
              <div class="prov">grounded in <code>{_esc(g.get('file'))}:{_esc(g.get('line_start'))}</code>
              ({_esc(g.get('source_type'))}) · class {_esc(f.law.get('evidence_class'))}
              · approval {_esc(f.law.get('approval'))}</div></td>
          <td><code>{_esc(f.export)}({_esc(_short(f.minimal_args, 48))})</code>
              <div class="obs">{_esc(_short(f.detail, 150))}</div></td>
          <td><code>tsx bde-repro-{_esc(f.finding_id)}.mjs</code></td>
        </tr>""")
    passed = "".join(f"<li><code>{_esc(o.law_id)}</code> · {_esc(o.predicate)} · {o.trials} trials</li>"
                     for o in result.outcomes if o.status == "PASS")
    not_checked = "".join(f"<li>{_esc(nc.get('reason'))}</li>" for nc in result.not_checked)
    return f"""<!doctype html><html><head><meta charset="utf-8">
<title>ShipGuard BDE — {_esc(result.module)}</title>
<style>
 body{{font-family:ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,sans-serif;margin:2rem;color:#111}}
 h1{{font-size:1.25rem}} .sub{{color:#555;margin-bottom:1.5rem}}
 table{{border-collapse:collapse;width:100%;margin:1rem 0}}
 th,td{{border:1px solid #ddd;padding:.5rem .6rem;vertical-align:top;text-align:left;font-size:.9rem}}
 th{{background:#f5f5f5}}
 .confirmed td{{background:#fff2f0}} .status{{font-weight:700;font-size:.75rem;margin-top:.3rem}}
 .prov{{color:#777;font-size:.78rem;margin-top:.25rem}} .obs{{color:#333;font-size:.8rem;margin-top:.25rem}}
 code{{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.82rem}}
 .cols{{display:flex;gap:2rem}} .cols>div{{flex:1}} ul{{padding-left:1.1rem;font-size:.85rem}}
 .ok{{color:#0a7d32}} .bad{{color:#b42318}}
</style></head><body>
<h1>Actenon ShipGuard — Behavioural Discovery result</h1>
<div class="sub">mode <b>{_esc(result.mode)}</b> · module <code>{_esc(result.module)}</code> ·
revision <code>{_esc(str(result.revision)[:12])}</code> · {result.tracked_files} tracked files ·
source repo untouched: <b>{_esc(result.original_untouched)}</b></div>
<p>Laws discovered <b>{result.laws_total}</b> · blocking-grade <b>{result.laws_blocking}</b> ·
hypotheses <b>{result.laws_hypotheses}</b> · preservation <b>{result.laws_preservation}</b> ·
executed <b>{result.executed}</b> (passed {result.passed}, violated {result.failed},
errored {result.errors}) in {result.duration_ms} ms.</p>
<h2>Findings ({len(result.findings)})</h2>
<table><tr><th>finding</th><th>violated law + provenance</th><th>witness</th><th>reproduce</th></tr>
{''.join(rows) or '<tr><td colspan="4">none — see scope notes</td></tr>'}</table>
<div class="cols"><div><h2>Checked &amp; passed</h2><ul>{passed or '<li>—</li>'}</ul></div>
<div><h2>Not checked / unknown</h2><ul>{not_checked or '<li>—</li>'}</ul></div></div>
<h2>Limitations</h2><ul>{''.join(f'<li>{_esc(x)}</li>' for x in result.limitations)}</ul>
</body></html>"""


def write_reports(result: BDEResult, out_dir: Path) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    term = out_dir / "bde-summary.txt"
    term.write_text(terminal_summary(result) + "\n")
    htm = out_dir / "bde-report.html"
    htm.write_text(html_report(result))
    jsn = out_dir / "bde-result.json"
    jsn.write_text(json.dumps({
        "schema": "actenon-shipguard/bde/result/1", "mode": result.mode, "module": result.module,
        "revision": result.revision, "overall_status": result.overall_status,
        "counts": {"laws_total": result.laws_total, "laws_blocking": result.laws_blocking,
                   "laws_hypotheses": result.laws_hypotheses, "laws_preservation": result.laws_preservation,
                   "executed": result.executed, "passed": result.passed, "failed": result.failed,
                   "errored": result.errors, "skipped": result.skipped},
        "findings": [f.to_dict() for f in result.findings],
        "not_checked": result.not_checked, "limitations": result.limitations,
        "original_untouched": result.original_untouched, "duration_ms": result.duration_ms,
    }, indent=2, ensure_ascii=False, default=str) + "\n")
    return {"summary": term, "html": htm, "json": jsn}

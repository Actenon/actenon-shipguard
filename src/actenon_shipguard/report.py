"""Self-contained offline HTML evidence report (mandate section 11).

No external JavaScript, hosted fonts, analytics or network calls. Failures are shown
with clear severity language, never hidden behind celebratory green cards.
"""
from __future__ import annotations

import html
import json
from pathlib import Path

_CSS = """
:root{--bg:#0f1115;--fg:#e6e6e6;--mut:#9aa4b2;--ok:#2ea44f;--bad:#d73a49;--warn:#d29922;--card:#161b22;--line:#30363d}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;padding:32px}
h1{font-size:22px;margin:0 0 4px}h2{font-size:16px;margin:28px 0 10px;color:var(--fg)}
.sub{color:var(--mut);margin:0 0 24px}.tag{display:inline-block;padding:2px 8px;border-radius:10px;font-size:12px;border:1px solid var(--line)}
table{width:100%;border-collapse:collapse;margin:8px 0}th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line);vertical-align:top}
th{color:var(--mut);font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:.04em}
code{background:#0b0e13;padding:1px 5px;border-radius:4px;font-size:12.5px}
.pill{font-weight:700;padding:2px 8px;border-radius:10px;font-size:12px}
.allow{background:rgba(46,164,79,.15);color:var(--ok);border:1px solid var(--ok)}
.refuse{background:rgba(215,58,73,.15);color:var(--bad);border:1px solid var(--bad)}
.card{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:16px;margin:10px 0}
.mut{color:var(--mut)}.kv{display:grid;grid-template-columns:220px 1fr;gap:4px 12px}
.warnbox{background:rgba(210,153,34,.1);border:1px solid var(--warn);border-radius:8px;padding:12px 16px;margin:16px 0;color:#f0d68a}
"""


def _esc(x) -> str:
    return html.escape(str(x))


def render_demo_report(summary: dict) -> str:
    rows = []
    for s in summary["scenarios"]:
        cls = "allow" if s["decision"] == "ALLOW" else "refuse"
        extra = ""
        if s.get("shares") is not None:
            extra = f"<div class='mut'>shares={_esc(s['shares'])} conserved={_esc(s['conserved'])}</div>"
        if s.get("property_verdict"):
            extra += f"<div class='mut'>property={_esc(s['property_verdict'])}</div>"
        if s.get("nonce_state"):
            extra += f"<div class='mut'>nonce_state={_esc(s['nonce_state'])} disbursement_written={_esc(s.get('disbursement_written'))}</div>"
        rows.append(
            f"<tr><td>{_esc(s['scenario'])}</td>"
            f"<td><span class='pill {cls}'>{_esc(s['decision'])}</span></td>"
            f"<td><code>{_esc(s['layer'])}/{_esc(s['code'])}</code>{extra}</td>"
            f"<td class='mut'>{_esc(s['reason'])}</td></tr>"
        )
    auth = summary.get("authority_signer", {})
    prov = summary.get("correctness_prover", {})
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Actenon ShipGuard — protected-execution evidence</title><style>{_CSS}</style></head><body>
<h1>Actenon ShipGuard <span class="tag">protected execution</span></h1>
<p class="sub">Your AI agent says it's done. ShipGuard checks before it ships. &mdash; mode: <code>{_esc(summary.get('mode'))}</code> &middot; {_esc(summary.get('generated_at'))}</p>

<div class="warnbox"><strong>Scope honesty.</strong> This is a cooperative local enforcement boundary, not an unbypassable OS sandbox. It proves the consequential action cannot traverse the <em>configured gate</em> without authorisation AND class-verified correctness AND exact-code binding AND a fresh nonce. See RELEASE-EVIDENCE.md for the full trust boundary and limitations.</div>

<h2>Enforcement boundary result</h2>
<table><thead><tr><th>Scenario</th><th>Decision</th><th>Layer / code</th><th>Reason</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table>

<h2>Separated signing authorities (pinned trust roots)</h2>
<div class="card"><div class="kv">
<div class="mut">Authority issuer (signs proofs)</div><div><code>Ed25519</code> key_id=<code>{_esc(auth.get('key_id'))}</code></div>
<div class="mut">Correctness prover (signs certs)</div><div><code>Ed25519</code> key_id=<code>{_esc(prov.get('key_id'))}</code></div>
<div class="mut">Trust roots file</div><div><code>{_esc(summary.get('trust_roots_file'))}</code></div>
<div class="mut">Property trials</div><div>{_esc(summary.get('property_trials'))} inputs (whole bug class, with shrinking)</div>
</div><p class="mut">The enforcer verifies against these externally pinned public keys; the coding agent holds no signing key and cannot forge a certificate or a gate authorization.</p></div>

<h2>What this proves &mdash; and what it does not</h2>
<div class="card"><ul>
<li><strong>Proves:</strong> a consequential action executed only when authorised (Actenon proof) AND class-verified-correct (independent certificate) AND the exact certified bytes ran (hash-bound) AND it was not a replay (durable nonce). Wrong-but-green, forged, substituted, stale, replaced, replayed, crashed and bypass attempts were all refused.</li>
<li><strong>Does not prove:</strong> arbitrary correctness from sampled inputs; unbypassable containment of a rogue agent that refuses to call the gate; exactly-once external effect under all crashes (an uncertain outcome is exposed and must be reconciled, never blind-retried).</li>
</ul></div>
<p class="mut">Generated offline by actenon-shipguard. No external assets, no network, no telemetry.</p>
</body></html>"""


def write_demo_report(summary: dict, path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_demo_report(summary), encoding="utf-8")
    return path


_STATUS_CLASS = {"verified": "allow", "contradicted": "refuse", "no_change": "refuse",
                 "environment_failure": "refuse", "interrupted": "refuse", "unverified": "refuse"}


def render_run_report(rec: dict) -> str:
    """Self-contained HTML report for a repair-loop run (mandate §11/§SIXTH).

    Shows the actual sequence: agent change -> ordinary tests -> independent Sentinel defect ->
    counterexample -> repair -> re-verification, with the structured receipt bindings. Failures are
    never hidden behind green cards. Live and offline-deterministic runs are clearly distinguished.
    """
    mode = rec.get("mode", "")
    live = mode == "live"
    mode_label = ("LIVE coding agent" if live else
                  "OFFLINE DETERMINISTIC (prewritten candidates — NOT a live model repair)")
    status = rec.get("final_status", "unverified")
    scls = _STATUS_CLASS.get(status, "refuse")
    attempts = rec.get("attempts") or []
    cx = rec.get("final_counterexample")

    # The aspirin headline: ordinary tests green on the initial defect, independent check disagreed.
    aspirin = rec.get("ordinary_tests_green_on_defect")
    headline = ""
    if aspirin:
        headline = ("<div class='warnbox'><strong>The point of ShipGuard.</strong> The agent's change passed "
                    "its ordinary tests, but independent Sentinel verification <em>contradicted</em> an approved "
                    "requirement and produced a reproducible counterexample.</div>")

    # Attempt rows.
    rows = []
    for a in attempts:
        ch = a.get("challenge") or {}
        ag = a.get("agent") or {}
        ot = a.get("ordinary_tests") or {}
        v = ch.get("verdict", "—")
        vcls = "allow" if ch.get("ok") else "refuse"
        rows.append(
            f"<tr><td>{_esc(a.get('attempt'))}</td>"
            f"<td>{_esc(ag.get('outcome'))}<div class='mut'>{_esc((ag.get('statement') or '')[:160])}</div></td>"
            f"<td>{_esc('passed' if ot.get('passed') else ('failed' if ot.get('passed') is False else 'n/a'))}"
            f"<div class='mut'>{_esc((ot.get('summary') or '').replace(chr(27), '')[:80])}</div></td>"
            f"<td><span class='pill {vcls}'>{_esc(v)}</span><div class='mut'>receipt {_esc(str(ch.get('receipt_hash'))[:12])}</div></td>"
            f"<td class='mut'>{_esc(ch.get('requirements'))}</td></tr>"
        )

    cx_html = ""
    if cx:
        cx_html = (f"<div class='card'><div class='kv'>"
                   f"<div class='mut'>Requirement</div><div><code>{_esc(cx.get('requirement_id'))}</code> — {_esc(cx.get('invariant'))}</div>"
                   f"<div class='mut'>Reproducing input</div><div><code>allocate({_esc(cx.get('input'))})</code></div>"
                   f"<div class='mut'>Expected</div><div><code>{_esc(cx.get('expected'))}</code></div>"
                   f"<div class='mut'>Observed</div><div><code>{_esc(cx.get('observed'))}</code></div>"
                   f"<div class='mut'>Why wrong</div><div>{_esc(cx.get('detail'))}</div>"
                   f"</div></div>")

    # Bindings from the last verified/contradicted challenge.
    bindings = {}
    for a in reversed(attempts):
        if (a.get("challenge") or {}).get("bindings"):
            bindings = a["challenge"]["bindings"]; break
    bind_html = "".join(
        f"<div class='mut'>{_esc(k)}</div><div><code>{_esc(v)}</code></div>"
        for k, v in bindings.items() if v is not None)

    states = " → ".join(rec.get("states") or [])
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Actenon ShipGuard — repair-loop evidence</title><style>{_CSS}</style></head><body>
<h1>Actenon ShipGuard <span class="tag">repair loop</span></h1>
<p class="sub">Your AI agent says it's done. ShipGuard checks before it ships. &mdash; agent: <code>{_esc(rec.get('agent'))}</code> &middot; {_esc(mode_label)}</p>

<div class="card"><div class="kv">
<div class="mut">Task</div><div>{_esc(rec.get('task'))}</div>
<div class="mut">Final status</div><div><span class="pill {scls}">{_esc(status.upper())}</span></div>
<div class="mut">Approved contract digest</div><div><code>{_esc(rec.get('contract_digest'))}</code></div>
<div class="mut">Verified candidate git head</div><div><code>{_esc(rec.get('git_head'))}</code></div>
</div></div>

{headline}

<h2>Lifecycle</h2>
<p class="mut"><code>{_esc(states)}</code></p>

<h2>Attempts (agent change → ordinary tests → independent Sentinel verification)</h2>
<table><thead><tr><th>#</th><th>Agent outcome</th><th>Ordinary tests</th><th>Sentinel verdict</th><th>Requirements</th></tr></thead>
<tbody>{''.join(rows) or '<tr><td colspan=5 class=mut>no attempts recorded</td></tr>'}</tbody></table>

<h2>Independent counterexample (what ordinary tests missed)</h2>
{cx_html or "<p class='mut'>No outstanding counterexample (either verified, or the defect was not reproduced).</p>"}

<h2>Verification bindings (structured Sentinel receipt)</h2>
<div class="card"><div class="kv">{bind_html or '<div class=mut>no receipt bindings</div>'}</div></div>

<h2>What this proves &mdash; and what it does not</h2>
<div class="card"><ul>
<li><strong>Proves:</strong> the final status was decided by independent Sentinel verification against a
developer-approved contract held out from the agent &mdash; not by the agent's own success claim or by its
ordinary tests. A contradicted requirement produced a reproducible counterexample; a verified repair
passed every approved requirement with full git + toolchain identity bound.</li>
<li><strong>Does not prove:</strong> arbitrary correctness beyond the approved examples/invariant seeds;
that a rogue agent which refuses to participate is stopped (this is a cooperative boundary). The
<code>local</code> runner executes candidate code under the same OS account and is advisory, not a
security sandbox.</li>
</ul></div>
<p class="mut">Generated offline by actenon-shipguard. No external assets, no network, no telemetry.</p>
</body></html>"""


def write_run_report(rec: dict, path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_run_report(rec), encoding="utf-8")
    return path

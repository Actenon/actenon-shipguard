"""actenon-shipguard CLI.

  actenon-shipguard init                 bootstrap pinned trust roots + config
  actenon-shipguard demo [--open]        deterministic offline protected-execution demo
  actenon-shipguard verify --cert ...    independently verify a correctness certificate
  actenon-shipguard report --out DIR     render the self-contained HTML evidence report
  actenon-shipguard doctor               environment diagnostics
  actenon-shipguard run "task" --agent   real coding-agent repair loop (see status)

Exit codes: 0 success/verified, 1 refused/contradiction/failed, 2 usage/environment error.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from . import __version__
from .orchestrator import run_task
from .pipeline import FIXTURES, run_demo
from .report import write_demo_report, write_run_report
from .sentinel import find_sentinel
from .trust import ROLE_CORRECTNESS, TrustRoots, generate_trust_roots


def _find_tsx(explicit: str | None) -> Path | None:
    if explicit:
        return Path(explicit)
    env = os.environ.get("SHIPGUARD_TSX")
    if env:
        return Path(env)
    which = shutil.which("tsx")
    if which:
        return Path(which)
    here = Path(__file__).resolve()
    for parent in here.parents:
        cand = parent / "sentinel-verified" / "node_modules" / ".bin" / "tsx"
        if cand.exists():
            return cand
        cand2 = parent / "node_modules" / ".bin" / "tsx"
        if cand2.exists():
            return cand2
    return None


def cmd_init(args) -> int:
    target = Path(args.dir).resolve()
    target.mkdir(parents=True, exist_ok=True)
    enforcement = args.enforcement

    if enforcement == "isolated":
        # FAIL CLOSED: hostile-agent-resistant isolation requires external key custody this build
        # does not integrate. Never pretend a same-user 0600 directory is isolation.
        custodian = os.environ.get("SHIPGUARD_KEY_CUSTODIAN")
        if not custodian:
            print("ERROR: --enforcement isolated requires external key custody "
                  "(SHIPGUARD_KEY_CUSTODIAN=kms://…|hsm://…|service://…). A same-OS-user 0600 directory "
                  "is NOT hostile-agent-resistant. Refusing to claim isolated mode without real custody.",
                  file=sys.stderr)
            return 2
        print("ERROR: an external custodian is configured but this build has no KMS/HSM/service signer "
              "integration yet, so isolated mode cannot be truthfully enforced. Use cooperative-local.",
              file=sys.stderr)
        return 2

    # cooperative-local: private keys OUTSIDE the agent's project workspace, 0600 (advisory).
    keys_dir = (Path(args.keys_dir).expanduser().resolve() if args.keys_dir
                else Path.home() / ".config" / "actenon-shipguard" / "keys")
    if str(keys_dir) == str(target) or str(keys_dir).startswith(str(target) + os.sep):
        print(f"ERROR: --keys-dir must be OUTSIDE the project workspace {target} (got {keys_dir})", file=sys.stderr)
        return 2

    roots, keypairs = generate_trust_roots(target / ".shipguard", keys_dir=keys_dir)
    config = {
        "schemaVersion": 1, "product": "actenon-shipguard", "version": __version__,
        "trust_roots": ".shipguard/trust-roots.json", "keys_dir": str(keys_dir),
        "authority_key_id": keypairs["authority"].key_id,
        "correctness_key_id": keypairs["correctness"].key_id,
        "reconciliation_key_id": keypairs["reconciliation"].key_id,
        "verifier_key_id": keypairs["verifier"].key_id,
        "enforcement": "cooperative-local",
        "enforcement_note": ("cooperative-local is ADVISORY: private keys live outside the project workspace "
                             "(0600) but a same-OS-user agent could still reach them. Not hostile-agent-resistant; "
                             "not an unbypassable sandbox. Isolated mode requires external KMS/HSM/service custody."),
    }
    (target / "shipguard.json").write_text(json.dumps(config, indent=2) + "\n")
    pem_in_workspace = [str(p) for p in target.rglob("*.pem")]
    tr = target / ".shipguard" / "trust-roots.json"
    print(f"initialised ShipGuard in {target}")
    print(f"  trust roots (public, in workspace) : {tr}")
    print(f"  private keys (OUTSIDE workspace)   : {keys_dir}")
    print(f"  authorities : authority={keypairs['authority'].key_id} correctness={keypairs['correctness'].key_id} "
          f"reconciliation={keypairs['reconciliation'].key_id} verifier={keypairs['verifier'].key_id}")
    print("  enforcement : cooperative-local (ADVISORY — not hostile-agent-resistant, not a sandbox)")
    print(f"  private keys inside workspace: {pem_in_workspace or 'NONE (good)'}")
    return 0 if not pem_in_workspace else 1


def cmd_demo(args) -> int:
    tsx = _find_tsx(args.tsx)
    if tsx is None or not Path(tsx).exists():
        print("ERROR: tsx not found. Install Node + tsx, or pass --tsx /path/to/tsx (or set SHIPGUARD_TSX).", file=sys.stderr)
        return 2
    out = Path(args.out).resolve()
    print(f"actenon-shipguard demo {__version__} — deterministic offline protected-execution matrix")
    print(f"  tsx={tsx}  trials={args.trials}  out={out}\n")
    summary = run_demo(out, tsx, trials=args.trials)
    report = write_demo_report(summary, out / "shipguard-report.html")
    refused = sum(1 for s in summary["scenarios"] if s["decision"] == "REFUSE")
    allowed = sum(1 for s in summary["scenarios"] if s["decision"] == "ALLOW")
    print(f"\n  {allowed} ALLOW (authorised + class-verified + mediated invocation) · {refused} REFUSE (forged/wrong/replaced/replayed/crashed/untrusted/bypass)")
    sumfile = out / "demo-summary.json"
    print(f"  evidence : {sumfile}")
    print(f"  report   : {report}")
    if args.open:
        _open(report)
    # The demo PASSES when the correct action is allowed and every attack is refused.
    ok = allowed >= 1 and refused >= 6
    print("DEMO RESULT:", "PASS" if ok else "CHECK ABOVE")
    return 0 if ok else 1


def cmd_verify(args) -> int:
    from .certs import Certificate, verify_certificate
    roots = TrustRoots.load(Path(args.trust_roots))
    cert = Certificate.from_dict(json.loads(Path(args.cert).read_text()))
    res = verify_certificate(cert, roots)
    print(json.dumps({"ok": res.ok, "overall": cert.overall, "reasons": res.reasons,
                      "code_artifact": cert.code_artifact_sha256, "digest": cert.digest}, indent=2))
    return 0 if (res.ok and cert.overall == "VERIFIED") else 1


def cmd_report(args) -> int:
    summary = json.loads((Path(args.out) / "demo-summary.json").read_text())
    report = write_demo_report(summary, Path(args.out) / "shipguard-report.html")
    print(f"report written: {report}")
    if args.open:
        _open(report)
    return 0


def cmd_doctor(args) -> int:
    print(f"actenon-shipguard {__version__} doctor")
    checks = []
    for name, fn in (("python>=3.11", lambda: sys.version_info >= (3, 11)),
                     ("node", lambda: shutil.which("node") is not None),
                     ("tsx", lambda: _find_tsx(None) is not None),
                     ("git", lambda: shutil.which("git") is not None)):
        ok = bool(fn()); checks.append(ok); print(f"  [{'ok' if ok else 'MISSING'}] {name}")
    import importlib.metadata as md
    for pkg in ("actenon-kernel", "actenon-protocol", "actenon-permit", "actenon-scan", "cryptography"):
        try:
            print(f"  [ok] {pkg}=={md.version(pkg)}")
        except Exception:
            print(f"  [MISSING] {pkg}"); checks.append(False)
    claude = shutil.which("claude"); codex = shutil.which("codex")
    print(f"  [{'ok' if claude else 'absent'}] claude CLI (real-agent mode){'' if claude else ' — offline demo still works'}")
    print(f"  [{'ok' if codex else 'absent'}] codex CLI (real-agent mode)")
    return 0 if all(checks) else 2


def _find_node_modules(explicit: str | None) -> Path | None:
    """Locate a node_modules providing vitest for the candidate repo's ordinary tests."""
    if explicit:
        p = Path(explicit).expanduser()
        return p if p.exists() else None
    env = os.environ.get("SHIPGUARD_NODE_MODULES")
    if env and Path(env).exists():
        return Path(env)
    here = Path(__file__).resolve()
    for parent in here.parents:
        for cand in (parent / "sentinel-verified" / "node_modules", parent / "node_modules"):
            if (cand / ".bin" / "vitest").exists():
                return cand
    return None


def _select_adapter(name: str):
    if name == "codex":
        from .adapters.codex import CodexAdapter
        return CodexAdapter()
    if name == "claude":
        from .adapters.claude import ClaudeAdapter
        return ClaudeAdapter()
    from .adapters.offline import OfflineAdapter
    return OfflineAdapter()


_EXIT_BY_STATUS = {"verified": 0, "contradicted": 1, "no_change": 1, "review_required": 1,
                   "environment_failure": 2, "interrupted": 2, "unverified": 1}


def cmd_run(args) -> int:
    task = (args.task or "").strip()
    if not task:
        print('ERROR: a task is required, e.g. actenon-shipguard run "Fix the payment allocation bug" --agent codex',
              file=sys.stderr)
        return 2

    adapter = _select_adapter(args.agent)
    sentinel_cli = find_sentinel(args.sentinel)
    node_modules = _find_node_modules(args.node_modules)
    live = adapter.mode == "live"
    banner = f"[LIVE agent: {adapter.name}]" if live else "[OFFLINE deterministic — NOT a live model repair]"

    print(f"actenon-shipguard run {banner}")
    print(f"  task        : {task}")
    print(f"  verifier    : sentinel={'ok' if sentinel_cli else 'MISSING'}  "
          f"node_modules={'ok' if node_modules else 'MISSING (ordinary tests skipped)'}  runner={args.runner}")

    # The real Sentinel verifier is mandatory for independent acceptance — never fall back to a
    # synthetic receipt for a live/production run, and never fabricate verification.
    if sentinel_cli is None:
        print("ERROR: the real Sentinel verifier is required for independent acceptance and was not found.\n"
              "       Set SHIPGUARD_SENTINEL=/path/to/sentinel/dist/cli.js (or put `sentinel` on PATH).",
              file=sys.stderr)
        return 2
    if live:
        ok, reason = adapter.available()
        if not ok:
            print(f"ERROR: agent '{args.agent}' is unavailable: {reason}", file=sys.stderr)
            print("       ShipGuard never fabricates model activity. Authenticate the agent (e.g. `codex login`),\n"
                  "       or use `--agent offline` for the labelled deterministic regression run.", file=sys.stderr)
            return 2

    out = Path(args.out)
    work = out / "tmp"                      # disposable (gitignored): candidate repo + verifier store
    approved = Path(args.contract).expanduser() if args.contract else None
    source_repo = Path(args.repo).expanduser() if args.repo else None
    if source_repo is not None and approved is None:
        print("ERROR: --repo (a real developer repository) requires an explicit --contract with the\n"
              "       developer-approved acceptance requirements. ShipGuard never invents acceptance\n"
              "       criteria from the agent's own output.", file=sys.stderr)
        return 2
    if source_repo is not None and not source_repo.exists():
        print(f"ERROR: --repo path does not exist: {source_repo}", file=sys.stderr)
        return 2
    mode_label = "real-repository (isolated clone)" if source_repo else "synthetic settlement fixture"
    print(f"  target      : {mode_label} · module={args.module} export={args.export}")

    rec = run_task(task=task, adapter=adapter, work=work, sentinel_cli=sentinel_cli,
                   approved_contract=approved, node_modules=node_modules,
                   max_attempts=args.max_attempts, agent_timeout=args.agent_timeout,
                   runner=args.runner, evidence_dir=out, source_repo=source_repo,
                   target_file=args.module, export=args.export)

    # Durable evidence: the run-record embeds the Sentinel receipt hash, bindings, verdicts and
    # counterexamples. The raw content-addressed receipt stays in the gitignored tmp store (it binds
    # absolute paths and is reproducible by re-running); we do not copy it into public evidence.
    report = write_run_report(rec.to_dict(), out / "shipguard-run-report.html")

    # Actionable terminal summary.
    print(f"\n  result      : {rec.final_status.upper()}  (agent={rec.agent}, mode={rec.mode})")
    print(f"  lifecycle   : {' -> '.join(rec.states)}")
    if rec.ordinary_tests_green_on_defect:
        print("  ASPIRIN     : ordinary tests were GREEN while independent Sentinel CONTRADICTED an approved requirement")
    if rec.final_counterexample:
        c = rec.final_counterexample
        print(f"  counterex.  : {c.get('requirement_id')} allocate({c.get('input')}) "
              f"expected {c.get('expected')} observed {c.get('observed')}")
    last = (rec.attempts[-1].get("challenge") if rec.attempts else {}) or {}
    if last.get("receipt_hash"):
        print(f"  receipt     : {last.get('receipt_hash')}")
    if rec.tree_binding:
        tb = rec.tree_binding
        print(f"  tree binding: commit {str(tb.get('commit'))[:12]} byte-identical to the verified "
              f"candidate: {tb.get('equivalent')} ({tb.get('files_checked')} files hash-matched)")
    if rec.original_untouched is not None:
        print(f"  source repo : original working tree untouched: {rec.original_untouched}")
    print(f"  evidence    : {out / 'run-record.json'}")
    print(f"  report      : {report}")
    if args.open:
        _open(report)
    code = _EXIT_BY_STATUS.get(rec.final_status, 1)
    print(f"RUN RESULT: {rec.final_status.upper()} (exit {code})")
    return code


def _open(path: Path) -> None:
    try:
        if sys.platform == "darwin":
            subprocess.run(["open", str(path)], check=False)
        elif shutil.which("xdg-open"):
            subprocess.run(["xdg-open", str(path)], check=False)
    except Exception:
        pass


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="actenon-shipguard", description="Your AI agent says it's done. ShipGuard checks before it ships.")
    ap.add_argument("--version", action="version", version=f"actenon-shipguard {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init", help="bootstrap pinned trust roots + config"); p.add_argument("--dir", default=".")
    p.add_argument("--enforcement", default="cooperative-local", choices=["cooperative-local", "isolated"],
                   help="cooperative-local (advisory) or isolated (fails closed without external KMS/HSM custody)")
    p.add_argument("--keys-dir", default=None,
                   help="directory for PRIVATE keys; MUST be outside the project workspace (default: ~/.config/actenon-shipguard/keys)")
    p.set_defaults(fn=cmd_init)
    p = sub.add_parser("demo", help="deterministic offline protected-execution demo")
    p.add_argument("--out", default=str(Path("evidence") / "shipguard-demo")); p.add_argument("--trials", type=int, default=200000)
    p.add_argument("--tsx", default=None); p.add_argument("--open", action="store_true"); p.set_defaults(fn=cmd_demo)
    p = sub.add_parser("verify", help="verify a correctness certificate against pinned trust roots")
    p.add_argument("--cert", required=True); p.add_argument("--trust-roots", required=True); p.set_defaults(fn=cmd_verify)
    p = sub.add_parser("report", help="render the HTML evidence report"); p.add_argument("--out", required=True); p.add_argument("--open", action="store_true"); p.set_defaults(fn=cmd_report)
    p = sub.add_parser("doctor", help="environment diagnostics"); p.set_defaults(fn=cmd_doctor)
    p = sub.add_parser("run", help="real coding-agent repair loop (independent Sentinel acceptance)")
    p.add_argument("task", nargs="?", default="")
    p.add_argument("--agent", default="offline", choices=["claude", "codex", "offline"])
    p.add_argument("--out", default=str(Path("evidence") / "shipguard-run"))
    p.add_argument("--max-attempts", type=int, default=2, help="bounded repair attempts (0 = no repair)")
    p.add_argument("--agent-timeout", type=int, default=600, help="per-attempt agent timeout (seconds)")
    p.add_argument("--runner", default="local", choices=["local", "docker"],
                   help="Sentinel verification runner (local is advisory; docker isolates)")
    p.add_argument("--sentinel", default=None, help="path to sentinel CLI (or set SHIPGUARD_SENTINEL)")
    p.add_argument("--node-modules", default=None, help="node_modules providing vitest (or set SHIPGUARD_NODE_MODULES)")
    p.add_argument("--contract", default=None,
                   help="path to the developer-approved Sentinel acceptance contract (held out from the agent)")
    p.add_argument("--repo", default=None,
                   help="run against a REAL JS/TS repository (cloned into a disposable isolated copy; "
                        "the original tree is never modified). Requires --contract.")
    p.add_argument("--module", default="src/settle.ts", help="target module path within the repository")
    p.add_argument("--export", default="allocate", help="exported function under verification")
    p.add_argument("--open", action="store_true"); p.set_defaults(fn=cmd_run)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())

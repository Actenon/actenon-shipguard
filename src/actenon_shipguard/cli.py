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
from .pipeline import FIXTURES, run_demo
from .report import write_demo_report
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
    roots, keypairs = generate_trust_roots(target / ".shipguard")
    config = {
        "schemaVersion": 1,
        "product": "actenon-shipguard",
        "version": __version__,
        "trust_roots": ".shipguard/trust-roots.json",
        "authority_key_id": keypairs["authority"].key_id,
        "correctness_key_id": keypairs["correctness"].key_id,
        "enforcement": "cooperative-local",
        "note": "Private keys are in .shipguard/keys (0600). Pin trust-roots.json outside the agent's writable scope in production.",
    }
    (target / "shipguard.json").write_text(json.dumps(config, indent=2) + "\n")
    tr = target / ".shipguard" / "trust-roots.json"
    ak = keypairs["authority"].key_id
    ck = keypairs["correctness"].key_id
    print(f"initialised ShipGuard in {target}")
    print(f"  trust roots : {tr}")
    print(f"  authority   : Ed25519 {ak}")
    print(f"  correctness : Ed25519 {ck}")
    print("  enforcement : cooperative-local (not an unbypassable sandbox)")
    return 0


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


def cmd_run(args) -> int:
    if args.agent in ("claude", "codex"):
        print(
            f"actenon-shipguard run --agent {args.agent}: the real coding-agent repair loop "
            "(edit -> ordinary tests -> independent challenge -> counterexample -> repair -> reverify)\n"
            "is NOT wired in this v0.1.0 pre-release. The trust boundary, offline demo and adversarial\n"
            "suite are complete and tested; the live Claude/Codex adapter is an explicit release blocker.\n"
            "Run `actenon-shipguard demo` for the deterministic protected-execution demonstration.",
            file=sys.stderr,
        )
        return 2
    # offline agent == the deterministic demo
    return cmd_demo(args)


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

    p = sub.add_parser("init", help="bootstrap pinned trust roots + config"); p.add_argument("--dir", default="."); p.set_defaults(fn=cmd_init)
    p = sub.add_parser("demo", help="deterministic offline protected-execution demo")
    p.add_argument("--out", default=str(Path("evidence") / "shipguard-demo")); p.add_argument("--trials", type=int, default=200000)
    p.add_argument("--tsx", default=None); p.add_argument("--open", action="store_true"); p.set_defaults(fn=cmd_demo)
    p = sub.add_parser("verify", help="verify a correctness certificate against pinned trust roots")
    p.add_argument("--cert", required=True); p.add_argument("--trust-roots", required=True); p.set_defaults(fn=cmd_verify)
    p = sub.add_parser("report", help="render the HTML evidence report"); p.add_argument("--out", required=True); p.add_argument("--open", action="store_true"); p.set_defaults(fn=cmd_report)
    p = sub.add_parser("doctor", help="environment diagnostics"); p.set_defaults(fn=cmd_doctor)
    p = sub.add_parser("run", help="real coding-agent repair loop"); p.add_argument("task", nargs="?", default="")
    p.add_argument("--agent", default="offline", choices=["claude", "codex", "offline"])
    p.add_argument("--out", default=str(Path("evidence") / "shipguard-demo")); p.add_argument("--trials", type=int, default=200000)
    p.add_argument("--tsx", default=None); p.add_argument("--open", action="store_true"); p.set_defaults(fn=cmd_run)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())

"""Real Sentinel integration (mandate §THIRD).

This module calls the *supported* Sentinel verifier (``sentinel verify``) against a candidate
repository and an externally-held approved contract, then consumes the STRUCTURED receipt from
the content-addressed store — never a terminal success string. The final acceptance decision is
Sentinel's, independently re-derived here from the receipt's checks and bound to:

  * the exact approved contract (deep-equality of the receipt's embedded contract),
  * the candidate source snapshot (``candidateHash``) and full Git identity (``git.head`` 40-hex),
  * the toolchain (``runtime.verifierVersion`` / ``vitest`` / ``workerSha256``) and ``runner``.

A task is VERIFIED only when mandatory ordinary tests pass, every approved requirement is covered
by a qualifying check, no preserved behaviour is contradicted, and no requirement is unresolved or
environment-failed. The offline synthetic receipts in ``pipeline.build_offline_sentinel_store`` are
a separately-labelled fixture and CANNOT authorise this production path.

Honest limitation (also recorded by Sentinel itself): the ``local`` runner executes candidate code
under the same OS account and is advisory, not a security boundary. Use ``runner="docker"`` with
``--allow-container`` for isolated execution where available.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SUPPORTED_SCHEMA_VERSIONS = {1, 2}
# Ordinary-test checks that MUST be VERIFIED before any task can be accepted.
MANDATORY_TEST_CHECKS = ("baseline-tests", "candidate-tests", "preserved-tests")
# Statuses that mean "not a clean pass" — never promote to verified.
_BAD_STATUSES = {"CONTRADICTED", "INCOMPLETE", "REVIEW_REQUIRED", "REVIEW", "ENVIRONMENT_FAILURE",
                 "UNKNOWN", "ERROR", "FAILED"}


def find_sentinel(explicit: str | None = None) -> list[str] | None:
    """Resolve the Sentinel CLI command prefix.

    Order: explicit path, ``$SHIPGUARD_SENTINEL``, ``sentinel`` on PATH, then the lab sibling
    repo's built ``dist/cli.js`` (run via node). Returns ``None`` when unavailable.
    """
    def _wrap(p: str) -> list[str]:
        return ["node", p] if p.endswith(".js") else [p]

    if explicit:
        return _wrap(explicit)
    env = os.environ.get("SHIPGUARD_SENTINEL")
    if env:
        return _wrap(env)
    which = shutil.which("sentinel")
    if which:
        return [which]
    here = Path(__file__).resolve()
    for parent in here.parents:
        cand = parent / "sentinel-verified" / "dist" / "cli.js"
        if cand.exists():
            return ["node", str(cand)]
    return None


@dataclass
class SentinelVerdict:
    ok: bool                       # True ONLY if independently re-derived VERIFIED acceptance
    status: str                    # Sentinel overall status (VERIFIED / CONTRADICTED / ...)
    receipt_hash: str = ""
    report_path: str = ""
    reasons: list[str] = field(default_factory=list)       # why not ok (actionable)
    counterexamples: list[dict] = field(default_factory=list)
    bindings: dict = field(default_factory=dict)           # contract/candidate/git/runtime/runner
    requirements: dict = field(default_factory=dict)       # id -> status
    ordinary_tests: dict = field(default_factory=dict)     # mandatory test checks -> status
    raw: dict = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "status": self.status, "receipt_hash": self.receipt_hash,
                "report_path": self.report_path, "reasons": self.reasons,
                "counterexamples": self.counterexamples, "bindings": self.bindings,
                "requirements": self.requirements, "ordinary_tests": self.ordinary_tests}


def _is_hex40(s: Any) -> bool:
    return isinstance(s, str) and len(s) == 40 and all(c in "0123456789abcdef" for c in s)


def _counterexample(check: dict) -> dict:
    return {
        "requirement_id": check.get("requirementId") or check.get("id"),
        "label": check.get("label"),
        "input": check.get("args", check.get("input")),
        "expected": check.get("expected"),
        "observed": check.get("observed"),
        "detail": check.get("detail") or check.get("message"),
    }


def evaluate_receipt(receipt: dict, approved_contract: dict, receipt_hash: str = "",
                     report_path: str = "") -> SentinelVerdict:
    """Independently re-derive acceptance from a structured Sentinel receipt.

    Never trusts the top-level ``status`` alone: it re-checks contract identity, git identity,
    requirement coverage, mandatory ordinary tests, and per-requirement outcomes.
    """
    reasons: list[str] = []
    checks = receipt.get("checks") or []
    by_id = {c.get("id"): c for c in checks if isinstance(c, dict)}

    # 1. Supported schema.
    sv = receipt.get("schemaVersion")
    if sv not in SUPPORTED_SCHEMA_VERSIONS:
        reasons.append(f"unsupported receipt schemaVersion={sv!r}")

    # 2. Exact approved-contract identity (canonicalization-independent deep equality).
    embedded = receipt.get("contract")
    if embedded != approved_contract:
        reasons.append("receipt contract does not deep-equal the approved contract (wrong/substituted contract)")

    # 3. Full Git identity + candidate snapshot binding.
    git = receipt.get("git") or {}
    if not _is_hex40(git.get("head")):
        reasons.append(f"receipt git.head is not a full 40-char commit sha: {git.get('head')!r}")
    if not receipt.get("candidateHash"):
        reasons.append("receipt has no candidateHash (candidate source not bound)")

    # 4. Real verifier/toolchain identity.
    runtime = receipt.get("runtime") or {}
    if not runtime.get("verifierVersion"):
        reasons.append("receipt runtime.verifierVersion missing (verifier identity unbound)")
    runner = receipt.get("runner")
    if not runner:
        reasons.append("receipt has no runner (verification provenance unbound)")

    # 5. Mandatory ordinary tests must be VERIFIED.
    ordinary: dict[str, str] = {}
    for cid in MANDATORY_TEST_CHECKS:
        c = by_id.get(cid)
        st = (c or {}).get("status", "MISSING")
        ordinary[cid] = st
        if st != "VERIFIED":
            reasons.append(f"mandatory ordinary-test check {cid!r} is {st} (must be VERIFIED)")

    # 6. Every approved requirement must be covered by a qualifying req: check, and VERIFIED.
    req_statuses: dict[str, str] = {}
    counterexamples: list[dict] = []
    for req in (approved_contract.get("requirements") or []):
        rid = req.get("id")
        rc = by_id.get(f"req:{rid}")
        if rc is None:
            reasons.append(f"approved requirement {rid!r} has no qualifying check (incomplete coverage)")
            req_statuses[rid] = "MISSING"
            continue
        st = rc.get("status", "UNKNOWN")
        req_statuses[rid] = st
        if st != "VERIFIED":
            reasons.append(f"requirement {rid!r} is {st}")
            if st in _BAD_STATUSES:
                counterexamples.append(_counterexample(rc))

    # 7. Any other contradicted/environment-failed check also blocks acceptance.
    for c in checks:
        st = c.get("status")
        cid = c.get("id", "")
        if st in _BAD_STATUSES and not cid.startswith("baseline:") and cid not in MANDATORY_TEST_CHECKS \
                and not cid.startswith("req:"):
            reasons.append(f"check {cid!r} is {st}")

    status = receipt.get("status", "UNKNOWN")
    ok = (status == "VERIFIED") and not reasons
    if status != "VERIFIED" and not any(status in r for r in reasons):
        reasons.insert(0, f"Sentinel overall status is {status} (not VERIFIED)")

    bindings = {
        "contractHash": receipt.get("contractHash"),
        "candidateHash": receipt.get("candidateHash"),
        "baselineHash": receipt.get("baselineHash"),
        "git_head": git.get("head"), "git_branch": git.get("branch"), "git_dirty": git.get("dirty"),
        "runner": runner, "verifierVersion": runtime.get("verifierVersion"),
        "vitest": runtime.get("vitest"), "node": runtime.get("node"),
        "workerSha256": runtime.get("workerSha256"),
    }
    return SentinelVerdict(ok=ok, status=status, receipt_hash=receipt_hash, report_path=report_path,
                           reasons=reasons, counterexamples=counterexamples, bindings=bindings,
                           requirements=req_statuses, ordinary_tests=ordinary, raw=receipt)


def run_sentinel_verify(*, repo: Path, contract_path: Path, store: Path, baseline: str = "HEAD",
                        sentinel: list[str] | str | None = None, allow_local: bool = True,
                        runner: str = "local", timeout: int = 300,
                        extra_args: list[str] | None = None) -> SentinelVerdict:
    """Run the real ``sentinel verify`` and return a structured, independently re-derived verdict.

    The contract and store live OUTSIDE the candidate repo (held-out from the coding agent).
    """
    cli = sentinel if isinstance(sentinel, list) else find_sentinel(sentinel)
    repo = Path(repo); contract_path = Path(contract_path); store = Path(store)
    if cli is None:
        return SentinelVerdict(ok=False, status="ENVIRONMENT_FAILURE",
                               reasons=["sentinel CLI not found (set SHIPGUARD_SENTINEL or install sentinel)"])
    if not contract_path.exists():
        return SentinelVerdict(ok=False, status="ENVIRONMENT_FAILURE",
                               reasons=[f"approved contract not found: {contract_path}"])
    store.mkdir(parents=True, exist_ok=True)
    approved_contract = json.loads(contract_path.read_text())

    cmd = [*cli, "verify", "--baseline", baseline, "--contract", str(contract_path),
           "--store", str(store), "--repo", str(repo), "--runner", runner]
    if allow_local and runner == "local":
        cmd.append("--allow-local")
    cmd += (extra_args or [])

    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           stdin=subprocess.DEVNULL, cwd=str(repo))
    except subprocess.TimeoutExpired:
        return SentinelVerdict(ok=False, status="ENVIRONMENT_FAILURE",
                               reasons=[f"sentinel verify timed out after {timeout}s"])
    except Exception as e:  # noqa: BLE001 - environment failure is a first-class verdict
        return SentinelVerdict(ok=False, status="ENVIRONMENT_FAILURE", reasons=[f"sentinel verify failed to run: {e}"])

    lv = store / "latest-verification.json"
    if not lv.exists():
        tail = ((p.stderr or "") + (p.stdout or ""))[-600:]
        return SentinelVerdict(ok=False, status="ENVIRONMENT_FAILURE",
                               reasons=[f"sentinel produced no receipt (exit {p.returncode}): {tail.strip()}"])
    try:
        ptr = json.loads(lv.read_text())
        receipt_hash = ptr["receipt"]
        receipt = json.loads((store / "objects" / receipt_hash).read_text())
    except Exception as e:  # noqa: BLE001
        return SentinelVerdict(ok=False, status="ENVIRONMENT_FAILURE",
                               reasons=[f"could not read structured receipt: {e}"])

    verdict = evaluate_receipt(receipt, approved_contract, receipt_hash=receipt_hash,
                               report_path=ptr.get("report", ""))
    # exit-code cross-check: 0 == scoped checks passed; 1 == contradiction/review/unknown; 2 == usage/infra.
    if p.returncode == 2 and verdict.status == "VERIFIED":
        verdict.ok = False
        verdict.reasons.append("sentinel exited 2 (usage/infrastructure error) despite a VERIFIED receipt")
    return verdict

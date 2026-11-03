"""Deterministic offline demonstration pipeline.

Runs the protected-execution trust boundary end to end using REAL property
verification (the bundled property_verify.mjs over 200k-class invariants) and REAL
mediated invocation (tsx imports the exact certified artifact and calls allocate()).
The Sentinel receipt in ``offline`` mode is a faithful content-addressed store built
locally so the demo is deterministic and needs no network/agent; ``run`` mode (real
Sentinel + a real coding agent) is the production path and is reported separately.

This is a demonstration of the enforcement boundary, not a claim that a cooperative
local wrapper is an unbypassable sandbox (see RELEASE-EVIDENCE.md).
"""
from __future__ import annotations

import json
import shutil
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .certs import build_certificate
from .gate import EdgeGate, ProtectedResource
from .nonce import NonceStore, ReplayRefused
from .proofs import AuthoritySigner, build_intent, mint_proof
from .receipts import verify_sentinel_receipt
from .trust import generate_trust_roots, sha256_hex

PKG = Path(__file__).resolve().parent
FIXTURES = PKG / "_bundled"
PROPERTY_VERIFY = PKG / "property_verify.mjs"
MODULE = "src/settle.ts"
EXPORT = "allocate"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _put_object(store: Path, payload: bytes) -> str:
    h = sha256_hex(payload)
    (store / "objects").mkdir(parents=True, exist_ok=True)
    (store / "objects" / h).write_bytes(payload)
    return h


def build_offline_sentinel_store(store: Path, repo: Path, contract: dict, head: str,
                                 *, status="VERIFIED", check_status="VERIFIED", verifier_kp=None) -> str:
    """Faithful content-addressed Sentinel store (object key == sha256 of stored bytes).

    LABELLED OFFLINE FIXTURE: when ``verifier_kp`` is supplied the receipt carries a demo
    verifier-authority attestation so the anti-fabrication path is exercised deterministically;
    this is a verifier-format fixture, NOT a genuine Sentinel run (see RELEASE-EVIDENCE.md).
    """
    store.mkdir(parents=True, exist_ok=True)
    src = (repo / MODULE).read_bytes()
    file_hash = _put_object(store, src)
    snapshot = {"schemaVersion": 1, "files": {MODULE: {"hash": file_hash, "size": len(src), "mode": 420}},
                "git": {"root": str(repo), "head": head, "branch": "main", "dirty": False}}
    candidate_hash = _put_object(store, json.dumps(snapshot, sort_keys=True).encode())
    contract_hash = _put_object(store, json.dumps(contract, sort_keys=True).encode())
    receipt = {"schemaVersion": 1, "id": str(uuid.uuid4()), "createdAt": _now(),
               "objective": contract.get("objective", ""), "baselineHash": candidate_hash,
               "candidateHash": candidate_hash, "contractHash": contract_hash, "git": snapshot["git"],
               "runner": "local-advisory", "runtime": {"verifierVersion": "1.0.0", "workerSha256": "w" * 64, "node": "v22"},
               "checks": [{"id": f"check-{r['id']}", "label": str(r.get("description", r["id"]))[:60],
                           "status": check_status, "detail": "", "requirementId": r["id"]}
                          for r in contract.get("requirements", [])],
               "changes": [], "status": status, "durationMs": 1, "limitations": [], "nextActions": []}
    if verifier_kp is not None:
        from .receipts import sign_receipt_attestation
        receipt = sign_receipt_attestation(verifier_kp, receipt)
    rh = _put_object(store, json.dumps(receipt, sort_keys=True).encode())
    (store / "latest-verification.json").write_text(json.dumps({"schemaVersion": 1, "receipt": rh, "report": ""}))
    return rh


def _git_head(repo: Path) -> str:
    return subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()


def _init_repo(tmp: Path, candidate: Path) -> Path:
    repo = tmp / f"repo-{uuid.uuid4().hex[:8]}"
    (repo / "src").mkdir(parents=True)
    shutil.copy(candidate, repo / MODULE)
    (repo / "package.json").write_text(json.dumps({"name": "t", "type": "module"}))
    # Umask-independence (see orchestrator.sync_file_modes_to_index): a copy made under umask 002
    # carries 0664 mode bits that turn every file into a mode-only "change" for the snapshot diff.
    (repo / MODULE).chmod(0o644)
    (repo / "package.json").chmod(0o644)
    for args in (["init", "-q"], ["config", "user.email", "t@t.local"], ["config", "user.name", "t"],
                 ["add", "-A"], ["commit", "-qm", "candidate"]):
        subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)
    return repo


def run_property(tsx: Path, code_path: Path, contract_path: Path, tmp: Path, trials: int = 200000) -> dict:
    contract = json.loads(Path(contract_path).read_text())
    contract["trials"] = trials
    cf = tmp / f"prop-{uuid.uuid4().hex[:6]}.json"
    cf.write_text(json.dumps(contract))
    out = subprocess.run([str(tsx), str(PROPERTY_VERIFY), "--module", str(code_path), "--contract", str(cf)],
                         capture_output=True, text=True)
    try:
        return json.loads(out.stdout)
    except json.JSONDecodeError:
        return {"verdict": "UNKNOWN", "trials": 0, "violations": [], "err": out.stderr[-300:]}


def _mint(tmp, roots, keypairs, contract, candidate, tsx, *, prover=None, status="VERIFIED",
          check_status="VERIFIED", trials=200000, code_for_exec=None):
    prover = prover or keypairs["correctness"]
    issuer = AuthoritySigner(keypairs["authority"])
    repo = _init_repo(tmp, candidate)
    head = _git_head(repo)
    store = tmp / f"store-{uuid.uuid4().hex[:6]}"
    build_offline_sentinel_store(store, repo, contract, head, status=status, check_status=check_status,
                                 verifier_kp=keypairs["verifier"])
    contract_file = tmp / f"c-{uuid.uuid4().hex[:6]}.json"
    contract_file.write_text(json.dumps(contract, sort_keys=True))
    rv = verify_sentinel_receipt(store=store, approved_contract=contract_file, candidate_repo=repo,
                                 module_path=MODULE, expected_head=head, verifier_roots=roots)
    prop = run_property(tsx, code_for_exec or (repo / MODULE), FIXTURES / "contracts" / "property-contract.json", tmp, trials)
    cdig = sha256_hex(json.dumps(contract, sort_keys=True).encode())
    cert = build_certificate(prover=prover, code_path=repo / MODULE, module_path=MODULE, export=EXPORT,
                             property_report=prop, receipt=rv, contract_digest=cdig, git_head=head)
    intent, now = build_intent(capability="settlement.disburse",
                               parameters={"total_pence": 1000000, "parties": 3, "allocation_id": "alloc-1"},
                               correctness_cert_digest=cert.digest, code_artifact_sha256=cert.code_artifact_sha256,
                               contract_digest=cdig, git_head=head, resource_id="ledger-1",
                               intent_id=f"intent-{uuid.uuid4().hex[:6]}")
    pccb = mint_proof(signer=issuer, intent_payload=intent, now=now,
                      pccb_id=f"pccb-{uuid.uuid4().hex[:6]}", nonce=f"nonce-{uuid.uuid4().hex[:8]}")
    return {"roots": roots, "keypairs": keypairs, "issuer": issuer, "repo": repo, "head": head, "store": store,
            "rv": rv, "prop": prop, "cert": cert, "intent": intent, "pccb": pccb.to_dict(), "now": now,
            "code": repo / MODULE, "contract_file": contract_file}


def _gate(tmp, a, tsx, out_dir):
    nonces = NonceStore(tmp / f"nonces-{uuid.uuid4().hex[:6]}.db")
    resource = ProtectedResource(trust_roots=a["roots"], tsx=tsx, out_dir=out_dir,
                                 nonce_store=nonces, ledger=out_dir / "ledger.jsonl")
    gate = EdgeGate(resource=resource)
    return gate, nonces, resource, out_dir


def _exec(gate, a, code_path=None):
    return gate.authorize_and_execute(
        intent_payload=a["intent"], pccb_payload=a["pccb"], cert=a["cert"], code_path=code_path or a["code"],
        module_path=MODULE, export=EXPORT, parameters={"total_pence": 1000000, "parties": 3, "allocation_id": "alloc-1"},
        resource_id="ledger-1", now=a["now"])


def run_demo(work_dir: Path, tsx: Path, *, trials: int = 200000) -> dict[str, Any]:
    """Run the protected-execution scenario matrix; return a machine-readable summary."""
    work = Path(work_dir); work.mkdir(parents=True, exist_ok=True)
    tmp = work / "tmp"; tmp.mkdir(exist_ok=True)
    contract = json.loads((FIXTURES / "contracts" / "settlement-contract.json").read_text())
    roots, keypairs = generate_trust_roots(work / "trust")
    ARM_A = FIXTURES / "candidates" / "arm-a-rounding.ts"
    ARM_B = FIXTURES / "candidates" / "arm-b-correct.ts"
    scenarios: list[dict[str, Any]] = []

    def record(name, decision, **extra):
        scenarios.append({"scenario": name, "decision": decision.decision, "layer": decision.layer,
                          "code": decision.code, "reason": decision.reason, **extra})
        print(f"  {name:48s} -> {decision.decision} [{decision.layer}/{decision.code}]")

    # 1. correct code: ALLOW via real mediated invocation
    aB = _mint(tmp, roots, keypairs, contract, ARM_B, tsx, trials=trials)
    outB = work / "out-correct"
    gB, nB, rB, _ = _gate(tmp, aB, tsx, outB)
    dB = _exec(gB, aB)
    disb = json.loads((outB / "disbursement.json").read_text()) if dB.allowed else None
    record("1 correct fix (authorised + class-verified)", dB, shares=disb and disb["shares"], conserved=disb and disb["conserved"])

    # 2. wrong code, green tests, valid authority: REFUSE on correctness
    aA = _mint(tmp, roots, keypairs, contract, ARM_A, tsx, trials=trials)
    gA, *_ = _gate(tmp, aA, tsx, work / "out-wrong")
    record("2 wrong fix, green tests, valid authority", _exec(gA, aA), property_verdict=aA["prop"]["verdict"])

    # 3. code replaced after certification: REFUSE hash mismatch
    g3, *_ = _gate(tmp, aB, tsx, work / "out-tamper")
    record("3 certified for B, executed bytes swapped to A", _exec(g3, aB, code_path=ARM_A))

    # 4. replay same nonce: REFUSE
    record("4 blind replay of the committed disbursement", _exec(gB, aB))

    # 5. uncertain outcome (crash mid-effect) then blind retry: REFUSE
    a5 = _mint(tmp, roots, keypairs, contract, ARM_B, tsx, trials=trials)
    out5 = work / "out-uncertain"
    g5, n5, r5, _ = _gate(tmp, a5, tsx, out5)
    r5._invoke_certified = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("simulated crash mid-effect"))
    d5a = _exec(g5, a5)
    record("5a crash mid-effect (nonce reserved, no record)", d5a, nonce_state=n5.get(a5["pccb"]["nonce"]).state,
           disbursement_written=(out5 / "disbursement.json").exists())
    r5._invoke_certified = ProtectedResource._invoke_certified.__get__(r5)
    record("5b blind retry of uncertain outcome", _exec(g5, a5))

    # 6. certificate signed by an unpinned (rogue) prover key: REFUSE
    from .trust import KeyPair
    rogue = KeyPair.generate("correctness", "rogue-prover-v1")
    a6 = _mint(tmp, roots, keypairs, contract, ARM_B, tsx, prover=rogue, trials=trials)
    g6, *_ = _gate(tmp, a6, tsx, work / "out-rogue")
    record("6 certificate signed by untrusted prover key", _exec(g6, a6))

    # 7. bypass: the enforcer holds NO signing key, and its only execute path re-verifies the
    #    primary evidence — a tampered proof presented directly to the resource is refused.
    import copy
    out7 = work / "out-bypass"
    _, _, r7, _ = _gate(tmp, aB, tsx, out7)
    holds_key = r7.holds_signing_key()
    tampered = copy.deepcopy(aB["pccb"])
    tampered["action"]["parameters"]["total_pence"] = 999  # breaks the signed action_hash
    d7 = r7.verify_and_execute(intent_payload=aB["intent"], pccb_payload=tampered, cert=aB["cert"],
                               code_path=aB["code"], module_path=MODULE, export=EXPORT,
                               parameters={"total_pence": 999, "parties": 3, "allocation_id": "alloc-1"},
                               resource_id="ledger-1", now=aB["now"])
    no_effect = not (out7 / "disbursement.json").exists()
    bypass_ok = (d7.decision == "REFUSE") and no_effect and (not holds_key)
    scenarios.append({"scenario": "7 enforcer is key-less; tampered proof refused at the only execute path",
                      "decision": d7.decision if bypass_ok else "ALLOW", "layer": "ENFORCEMENT",
                      "code": "KEYLESS_ENFORCER" if bypass_ok else "ENFORCER_HAS_KEY_OR_BYPASSED",
                      "reason": f"holds_signing_key={holds_key}; decision={d7.decision}; side_effect_written={not no_effect}"})
    print(f"  {'7 enforcer key-less + tampered proof refused':48s} -> {d7.decision} (holds_signing_key={holds_key})")

    summary = {
        "mode": "offline-deterministic",
        "generated_at": _now(),
        "authority_signer": {"algorithm": "Ed25519", "key_id": keypairs["authority"].key_id},
        "correctness_prover": {"algorithm": "Ed25519", "key_id": keypairs["correctness"].key_id},
        # Portable reference relative to the demo output dir — never an absolute local path in public evidence.
        "trust_roots_file": "trust/trust-roots.json",
        "property_trials": trials,
        "scenarios": scenarios,
    }
    (work / "demo-summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    return summary

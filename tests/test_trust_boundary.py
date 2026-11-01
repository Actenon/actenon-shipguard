"""Adversarial trust-boundary tests (mandate sections 6 and 13).

Every test asserts a REFUSAL (or a single mediated ALLOW) established independently —
never by matching a string in stdout. A content-addressed Sentinel store is built the
way Sentinel builds it (object key == sha256 of the stored bytes) so each field can be
forged/tampered precisely and the verifier's rejection proven.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from actenon_shipguard import (
    AuthoritySigner, Certificate, EdgeGate, KeyPair, NonceStore, ProtectedResource,
    ReplayRefused, TrustRoots,build_certificate, build_intent, generate_trust_roots,
    mint_proof, verify_sentinel_receipt,
)
from actenon_shipguard.certs import verify_certificate
from actenon_shipguard.proofs import AuthorityVerifier
from actenon_shipguard.cli import _find_tsx

PKG = Path(__file__).resolve().parents[1]
FIXTURES = PKG / "fixtures"
# Resolve tsx portably: SHIPGUARD_TSX env, PATH (CI installs it globally), or the lab sibling repo.
TSX = _find_tsx(None)
PROPERTY_VERIFY = PKG / "src" / "actenon_shipguard" / "property_verify.mjs"
MODULE = "src/settle.ts"
EXPORT = "allocate"

pytestmark = pytest.mark.skipif(
    TSX is None or not Path(TSX).exists(),
    reason="tsx not available (install Node + tsx, or set SHIPGUARD_TSX)",
)


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def put_object(store: Path, payload: bytes) -> str:
    h = sha(payload)
    (store / "objects").mkdir(parents=True, exist_ok=True)
    (store / "objects" / h).write_bytes(payload)
    return h


# --------------------------------------------------------------------------- #
# Build a faithful content-addressed Sentinel store for a candidate repo
# --------------------------------------------------------------------------- #
def build_sentinel_store(store: Path, repo: Path, contract: dict, *, status="VERIFIED",
                         check_status="VERIFIED", head: str | None = None,
                         contract_override: dict | None = None) -> str:
    store = Path(store); store.mkdir(parents=True, exist_ok=True)
    src = (repo / MODULE).read_bytes()
    file_hash = put_object(store, src)
    head = head or _git_head(repo)
    snapshot = {"schemaVersion": 1, "files": {MODULE: {"hash": file_hash, "size": len(src), "mode": 420}},
                "git": {"root": str(repo), "head": head, "branch": "main", "dirty": False}}
    candidate_hash = put_object(store, json.dumps(snapshot, sort_keys=True).encode())
    stored_contract = contract_override if contract_override is not None else contract
    contract_hash = put_object(store, json.dumps(stored_contract, sort_keys=True).encode())
    checks = [{"id": "req-1", "label": "behaviour", "status": check_status, "detail": "", "requirementId": "valid-ages"}]
    receipt = {"schemaVersion": 1, "id": str(uuid.uuid4()), "createdAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
               "objective": contract.get("objective", ""), "baselineHash": candidate_hash, "candidateHash": candidate_hash,
               "contractHash": contract_hash, "git": snapshot["git"], "runner": "local-advisory",
               "runtime": {"verifierVersion": "1.0.0", "workerSha256": "w" * 64, "node": "v22"},
               "checks": checks, "changes": [], "status": status, "durationMs": 1, "limitations": [], "nextActions": []}
    receipt_hash = put_object(store, json.dumps(receipt, sort_keys=True).encode())
    (store / "latest-verification.json").write_text(json.dumps({"schemaVersion": 1, "receipt": receipt_hash, "report": ""}))
    return receipt_hash


def _git_head(repo: Path) -> str:
    return subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()


def _git_init_candidate(tmp: Path, candidate: Path, contract: dict) -> Path:
    repo = tmp / f"repo-{uuid.uuid4().hex[:8]}"
    (repo / "src").mkdir(parents=True)
    shutil.copy(candidate, repo / MODULE)
    (repo / "package.json").write_text(json.dumps({"name": "t", "type": "module"}))
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "t@t.local"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "t"], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "c"], check=True)
    return repo


def run_property(code_path: Path, tmp: Path) -> dict:
    contract = json.loads((FIXTURES / "contracts" / "property-contract.json").read_text())
    contract["trials"] = 250
    contract["exhaustiveSmallGrid"] = {"totalPence": [0, 1, 2, 3, 5, 7, 10], "parties": [1, 2, 3]}
    cf = tmp / f"prop-{uuid.uuid4().hex[:6]}.json"
    cf.write_text(json.dumps(contract))
    out = subprocess.run([str(TSX), str(PROPERTY_VERIFY), "--module", str(code_path), "--contract", str(cf)],
                         capture_output=True, text=True)
    try:
        return json.loads(out.stdout)
    except json.JSONDecodeError:
        return {"verdict": "UNKNOWN", "trials": 0, "violations": [], "err": out.stderr[-300:]}


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture
def trust(tmp_path):
    roots, keypairs = generate_trust_roots(tmp_path / "trust")
    return roots, keypairs


@pytest.fixture
def contract():
    return json.loads((FIXTURES / "contracts" / "settlement-contract.json").read_text())


def make_action(tmp_path, trust, contract, candidate, *, status="VERIFIED", check_status="VERIFIED",
                prover=None, contract_override=None, code_for_exec=None):
    """Full mint: real sentinel store + real property-verify -> cert -> proof."""
    roots, keypairs = trust
    prover = prover or keypairs["correctness"]
    issuer = AuthoritySigner(keypairs["authority"])
    repo = _git_init_candidate(tmp_path, candidate, contract)
    head = _git_head(repo)
    store = tmp_path / f"store-{uuid.uuid4().hex[:6]}"
    receipt_hash = build_sentinel_store(store, repo, contract, status=status, check_status=check_status,
                                        head=head, contract_override=contract_override)
    rv = verify_sentinel_receipt(store=store, approved_contract=json.dumps(contract) and _contract_file(tmp_path, contract),
                                 candidate_repo=repo, module_path=MODULE, expected_head=head)
    prop = run_property(code_for_exec or (repo / MODULE), tmp_path)
    cert = build_certificate(prover=prover, code_path=repo / MODULE, module_path=MODULE, export=EXPORT,
                             property_report=prop, receipt=rv, contract_digest=sha(json.dumps(contract, sort_keys=True).encode()),
                             git_head=head)
    intent, now = build_intent(capability="settlement.disburse",
                               parameters={"total_pence": 1000000, "parties": 3, "allocation_id": "alloc-1"},
                               correctness_cert_digest=cert.digest, code_artifact_sha256=cert.code_artifact_sha256,
                               contract_digest=sha(json.dumps(contract, sort_keys=True).encode()), git_head=head,
                               resource_id="ledger-1", intent_id=f"intent-{uuid.uuid4().hex[:6]}")
    pccb = mint_proof(signer=issuer, intent_payload=intent, now=now,
                      pccb_id=f"pccb-{uuid.uuid4().hex[:6]}", nonce=f"nonce-{uuid.uuid4().hex[:8]}")
    return {"roots": roots, "keypairs": keypairs, "issuer": issuer, "repo": repo, "head": head,
            "store": store, "rv": rv, "prop": prop, "cert": cert, "intent": intent,
            "pccb": pccb.to_dict(), "now": now, "code": repo / MODULE, "receipt_hash": receipt_hash}


def _contract_file(tmp_path, contract) -> Path:
    p = tmp_path / f"contract-{uuid.uuid4().hex[:6]}.json"
    p.write_text(json.dumps(contract, sort_keys=True))
    return p


def make_gate(tmp_path, action, tsx=TSX):
    nonce_store = NonceStore(tmp_path / f"nonces-{uuid.uuid4().hex[:6]}.db")
    out_dir = tmp_path / f"out-{uuid.uuid4().hex[:6]}"
    resource = ProtectedResource(trust_roots=action["roots"], authority_key_id=action["issuer"].key_id,
                                 tsx=tsx, out_dir=out_dir)
    gate = EdgeGate(trust_roots=action["roots"], issuer_signer=action["issuer"], nonce_store=nonce_store,
                    resource=resource, ledger=out_dir / "ledger.jsonl")
    return gate, nonce_store, resource, out_dir


def run_gate(gate, action, code_path=None):
    return gate.authorize_and_execute(
        intent_payload=action["intent"], pccb_payload=action["pccb"], cert=action["cert"],
        code_path=code_path or action["code"], module_path=MODULE, export=EXPORT,
        parameters={"total_pence": 1000000, "parties": 3, "allocation_id": "alloc-1"},
        resource_id="ledger-1", now=action["now"])


ARM_A = FIXTURES / "candidates" / "arm-a-rounding.ts"
ARM_B = FIXTURES / "candidates" / "arm-b-correct.ts"


# --------------------------------------------------------------------------- #
# TESTS
# --------------------------------------------------------------------------- #
def test_allow_correct_code_mediates_real_invocation(tmp_path, trust, contract):
    a = make_action(tmp_path, trust, contract, ARM_B)
    assert a["prop"]["verdict"] == "VERIFIED" and a["rv"].ok, (a["prop"], a["rv"].reasons)
    gate, nonces, resource, out = make_gate(tmp_path, a)
    d = run_gate(gate, a)
    assert d.allowed, d
    disb = json.loads((out / "disbursement.json").read_text())
    assert disb["conserved"] is True and sum(disb["shares"]) == 1000000  # produced BY the certified code
    assert nonces.get(a["pccb"]["nonce"]).state == "committed"


def test_refuse_wrong_code_despite_valid_authority(tmp_path, trust, contract):
    a = make_action(tmp_path, trust, contract, ARM_A)  # property VIOLATED
    assert a["prop"]["verdict"] == "VIOLATED"
    gate, *_ = make_gate(tmp_path, a)
    d = run_gate(gate, a)
    assert d.decision == "REFUSE" and d.layer == "CORRECTNESS" and d.code == "NOT_VERIFIED", d


def test_refuse_forged_receipt_status(tmp_path, trust, contract):
    # A genuinely-CONTRADICTED receipt is forged to claim VERIFIED. The rewrite changes
    # the stored bytes, so the content-address (sha256(bytes)==object key) no longer holds.
    a = make_action(tmp_path, trust, contract, ARM_B, status="CONTRADICTED", check_status="CONTRADICTED")
    obj = a["store"] / "objects" / a["receipt_hash"]
    forged = json.loads(obj.read_text())
    assert forged["status"] == "CONTRADICTED"  # the honest result before forgery
    forged["status"] = "VERIFIED"
    forged["checks"][0]["status"] = "VERIFIED"
    obj.write_text(json.dumps(forged, sort_keys=True))  # key no longer matches sha256(bytes)
    rv = verify_sentinel_receipt(store=a["store"], approved_contract=_contract_file(tmp_path, contract),
                                 candidate_repo=a["repo"], module_path=MODULE, expected_head=a["head"])
    assert not rv.ok and any("FORGED" in r or "integrity" in r for r in rv.reasons), rv.reasons


def test_refuse_contract_substitution(tmp_path, trust, contract):
    evil = json.loads(json.dumps(contract)); evil["objective"] = "steal everything"
    a = make_action(tmp_path, trust, contract, ARM_B, contract_override=evil)
    # receipt's stored contract != the approved contract the verifier checks against
    assert not a["rv"].ok and any("CONTRACT_SUBSTITUTION" in r for r in a["rv"].reasons), a["rv"].reasons


def test_refuse_code_replaced_after_certification(tmp_path, trust, contract):
    a = make_action(tmp_path, trust, contract, ARM_B)  # certified for arm-B
    gate, *_ = make_gate(tmp_path, a)
    d = run_gate(gate, a, code_path=ARM_A)  # but arm-A bytes are presented for execution
    assert d.decision == "REFUSE" and d.code == "CODE_ARTIFACT_MISMATCH", d


def test_refuse_certificate_signed_by_untrusted_key(tmp_path, trust, contract):
    roots, keypairs = trust
    rogue = KeyPair.generate("correctness", "rogue-prover-v1")  # NOT pinned in trust roots
    a = make_action(tmp_path, trust, contract, ARM_B, prover=rogue)
    cv = verify_certificate(a["cert"], roots)
    assert not cv.ok and any("UNTRUSTED_PROVER" in r for r in cv.reasons), cv.reasons
    gate, *_ = make_gate(tmp_path, a)
    d = run_gate(gate, a)
    assert d.decision == "REFUSE" and d.layer == "CORRECTNESS", d


def test_refuse_stale_receipt_source_mismatch(tmp_path, trust, contract):
    a = make_action(tmp_path, trust, contract, ARM_B)
    # mutate the candidate source after the receipt was issued -> snapshot file hash no longer matches
    (a["repo"] / MODULE).write_text((a["repo"] / MODULE).read_text() + "\n// drifted\n")
    rv = verify_sentinel_receipt(store=a["store"], approved_contract=_contract_file(tmp_path, contract),
                                 candidate_repo=a["repo"], module_path=MODULE, expected_head=a["head"])
    assert not rv.ok and any("STALE" in r or "CODE_REPLACED" in r for r in rv.reasons), rv.reasons


def test_refuse_replay_same_nonce(tmp_path, trust, contract):
    a = make_action(tmp_path, trust, contract, ARM_B)
    gate, nonces, *_ = make_gate(tmp_path, a)
    assert run_gate(gate, a).allowed
    d2 = run_gate(gate, a)  # same nonce, blind re-dispatch
    assert d2.decision == "REFUSE" and d2.layer == "REPLAY" and d2.code == "NONCE_REUSED", d2


def test_concurrent_nonce_only_one_wins(tmp_path):
    db = tmp_path / "race.db"
    results = []
    def claim():
        s = NonceStore(db)
        try:
            s.reserve(nonce="shared", pccb_id="p", effect_id="e"); results.append("won")
        except ReplayRefused:
            results.append("lost")
        finally:
            s.close()
    ts = [threading.Thread(target=claim) for _ in range(8)]
    [t.start() for t in ts]; [t.join() for t in ts]
    assert results.count("won") == 1, results


def test_uncertain_outcome_refuses_blind_retry(tmp_path, trust, contract):
    a = make_action(tmp_path, trust, contract, ARM_B)
    gate, nonces, resource, out = make_gate(tmp_path, a)
    # simulate a crash mid-effect: invocation raises AFTER the nonce was reserved
    resource._invoke_certified = lambda *args, **kw: (_ for _ in ()).throw(RuntimeError("crash mid-effect"))
    d1 = run_gate(gate, a)
    assert d1.decision == "REFUSE" and d1.code == "EFFECT_UNCERTAIN", d1
    assert nonces.get(a["pccb"]["nonce"]).state == "reserved"
    assert not (out / "disbursement.json").exists()  # no side effect recorded
    # blind retry must be refused, not re-executed
    resource._invoke_certified = ProtectedResource._invoke_certified.__get__(resource)
    d2 = run_gate(gate, a)
    assert d2.decision == "REFUSE" and d2.layer == "REPLAY" and d2.code == "UNCERTAIN_OUTCOME", d2


def test_nonce_store_survives_restart(tmp_path):
    db = tmp_path / "durable.db"
    s1 = NonceStore(db); s1.reserve(nonce="n1", pccb_id="p", effect_id="e"); s1.commit(nonce="n1", outcome={"ok": 1}); s1.close()
    s2 = NonceStore(db)  # reopen after 'crash/restart'
    with pytest.raises(ReplayRefused) as ei:
        s2.reserve(nonce="n1", pccb_id="p", effect_id="e")
    assert ei.value.code == "NONCE_REUSED"
    s2.close()


def test_bypass_resource_without_authorization_refused(tmp_path, trust, contract):
    a = make_action(tmp_path, trust, contract, ARM_B)
    gate, nonces, resource, out = make_gate(tmp_path, a)
    from actenon_shipguard.gate import GateAuthorization
    forged = GateAuthorization(nonce="x", code_artifact_sha256=a["cert"].code_artifact_sha256, module_path=MODULE,
                               export=EXPORT, parameters={"total_pence": 1000000, "parties": 3}, resource_id="ledger-1",
                               expires_at="2099-01-01T00:00:00Z", signature="")
    with pytest.raises(PermissionError):
        resource.execute(forged, a["code"])  # no valid issuer signature -> refused, no side effect
    assert not (out / "disbursement.json").exists()


def test_authority_proof_tamper_refused(tmp_path, trust, contract):
    a = make_action(tmp_path, trust, contract, ARM_B)
    a["pccb"]["action"]["constraints"]["correctness_cert"] = "sha256:" + "0" * 64  # rebind to a different cert
    gate, *_ = make_gate(tmp_path, a)
    d = run_gate(gate, a)
    assert d.decision == "REFUSE" and d.layer == "AUTHORITY", d  # action_hash no longer matches signature

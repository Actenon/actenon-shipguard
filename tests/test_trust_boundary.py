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
from actenon_shipguard.nonce import ReconciliationVerifier, sign_reconciliation_statement, RESERVED
from actenon_shipguard.trust import (
    sign_domain, verify_domain, DOMAIN_CORRECTNESS_CERT, DOMAIN_RECONCILIATION,
)

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
                         contract_override: dict | None = None, checks_override=None) -> str:
    store = Path(store); store.mkdir(parents=True, exist_ok=True)
    src = (repo / MODULE).read_bytes()
    file_hash = put_object(store, src)
    head = head or _git_head(repo)
    snapshot = {"schemaVersion": 1, "files": {MODULE: {"hash": file_hash, "size": len(src), "mode": 420}},
                "git": {"root": str(repo), "head": head, "branch": "main", "dirty": False}}
    candidate_hash = put_object(store, json.dumps(snapshot, sort_keys=True).encode())
    stored_contract = contract_override if contract_override is not None else contract
    contract_hash = put_object(store, json.dumps(stored_contract, sort_keys=True).encode())
    checks = checks_override if checks_override is not None else [
        {"id": f"check-{r['id']}", "label": str(r.get("description", r["id"]))[:60],
         "status": check_status, "detail": "", "requirementId": r["id"]}
        for r in contract.get("requirements", [])]
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
    resource = ProtectedResource(trust_roots=action["roots"], tsx=tsx, out_dir=out_dir,
                                 nonce_store=nonce_store, ledger=out_dir / "ledger.jsonl")
    gate = EdgeGate(resource=resource)
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


def test_enforcer_keyless_and_tampered_proof_refused(tmp_path, trust, contract):
    import copy
    a = make_action(tmp_path, trust, contract, ARM_B)
    gate, nonces, resource, out = make_gate(tmp_path, a)
    # P0 signing separation: the enforcer / protected resource holds NO private signing material.
    assert resource.holds_signing_key() is False
    assert not hasattr(gate, "_issuer") and not hasattr(gate, "_signer")
    # The only execute path re-verifies the primary evidence; a tampered proof is refused, no side effect.
    tampered = copy.deepcopy(a["pccb"]); tampered["action"]["parameters"]["total_pence"] = 999
    d = resource.verify_and_execute(
        intent_payload=a["intent"], pccb_payload=tampered, cert=a["cert"], code_path=a["code"],
        module_path=MODULE, export=EXPORT,
        parameters={"total_pence": 999, "parties": 3, "allocation_id": "alloc-1"},
        resource_id="ledger-1", now=a["now"])
    assert d.decision == "REFUSE" and d.layer == "AUTHORITY", d
    assert not (out / "disbursement.json").exists()


def test_authority_proof_tamper_refused(tmp_path, trust, contract):
    a = make_action(tmp_path, trust, contract, ARM_B)
    a["pccb"]["action"]["constraints"]["correctness_cert"] = "sha256:" + "0" * 64  # rebind to a different cert
    gate, *_ = make_gate(tmp_path, a)
    d = run_gate(gate, a)
    assert d.decision == "REFUSE" and d.layer == "AUTHORITY", d  # action_hash no longer matches signature


# --------------------------------------------------------------------------- #
# P0 authorisation binding: executed action must EXACTLY equal the verified intent
# --------------------------------------------------------------------------- #
def _exec_with(gate, a, *, parameters=None, export=EXPORT, module_path=MODULE,
               resource_id="ledger-1", code_path=None):
    return gate.authorize_and_execute(
        intent_payload=a["intent"], pccb_payload=a["pccb"], cert=a["cert"],
        code_path=code_path or a["code"], module_path=module_path, export=export,
        parameters=parameters or {"total_pence": 1000000, "parties": 3, "allocation_id": "alloc-1"},
        resource_id=resource_id, now=a["now"])


def test_refuse_small_authorisation_reused_for_larger_action(tmp_path, trust, contract):
    # A valid proof authorises total_pence=1_000_000; the caller requests 100_000_000.
    a = make_action(tmp_path, trust, contract, ARM_B)
    gate, nonces, resource, out = make_gate(tmp_path, a)
    d = _exec_with(gate, a, parameters={"total_pence": 100000000, "parties": 3, "allocation_id": "alloc-1"})
    assert d.decision == "REFUSE" and d.layer == "AUTHORITY" and d.code == "INTENT_MISMATCH", d
    assert not (out / "disbursement.json").exists()      # protected resource NEVER invoked
    assert nonces.get(a["pccb"]["nonce"]) is None        # refused BEFORE nonce reservation / side effect


def test_refuse_export_substitution_same_module(tmp_path, trust, contract):
    # Certificate certifies export `allocate`; caller tries to execute a different export.
    a = make_action(tmp_path, trust, contract, ARM_B)
    gate, nonces, resource, out = make_gate(tmp_path, a)
    d = _exec_with(gate, a, export="formatPence")
    assert d.decision == "REFUSE" and d.code == "INTENT_MISMATCH", d
    assert not (out / "disbursement.json").exists()
    assert nonces.get(a["pccb"]["nonce"]) is None


def test_refuse_resource_substitution(tmp_path, trust, contract):
    a = make_action(tmp_path, trust, contract, ARM_B)
    gate, nonces, resource, out = make_gate(tmp_path, a)
    d = _exec_with(gate, a, resource_id="attacker-controlled-ledger")
    assert d.decision == "REFUSE" and d.code == "INTENT_MISMATCH", d
    assert not (out / "disbursement.json").exists()
    assert nonces.get(a["pccb"]["nonce"]) is None


def test_refuse_module_path_substitution(tmp_path, trust, contract):
    a = make_action(tmp_path, trust, contract, ARM_B)
    gate, nonces, resource, out = make_gate(tmp_path, a)
    d = _exec_with(gate, a, module_path="src/other.ts")
    assert d.decision == "REFUSE" and d.code == "INTENT_MISMATCH", d
    assert not (out / "disbursement.json").exists()


# --------------------------------------------------------------------------- #
# P0 Sentinel receipt soundness: coverage, matching ids, no fabricated VERIFIED
# --------------------------------------------------------------------------- #
def test_receipt_zero_checks_rejected(tmp_path, contract):
    repo = _git_init_candidate(tmp_path, ARM_B, contract)
    head = _git_head(repo)
    store = tmp_path / "store-zero"
    build_sentinel_store(store, repo, contract, head=head, checks_override=[])
    rv = verify_sentinel_receipt(store=store, approved_contract=_contract_file(tmp_path, contract),
                                 candidate_repo=repo, module_path=MODULE, expected_head=head)
    assert not rv.ok and any("zero checks" in r for r in rv.reasons), rv.reasons


def test_receipt_unrelated_requirement_id_rejected(tmp_path, contract):
    repo = _git_init_candidate(tmp_path, ARM_B, contract)
    head = _git_head(repo)
    store = tmp_path / "store-unrelated"
    checks = [{"id": f"check-{r['id']}", "label": "x", "status": "VERIFIED", "detail": "", "requirementId": r["id"]}
              for r in contract.get("requirements", [])]
    checks.append({"id": "rogue", "label": "x", "status": "VERIFIED", "detail": "", "requirementId": "not-a-real-requirement"})
    build_sentinel_store(store, repo, contract, head=head, checks_override=checks)
    rv = verify_sentinel_receipt(store=store, approved_contract=_contract_file(tmp_path, contract),
                                 candidate_repo=repo, module_path=MODULE, expected_head=head)
    assert not rv.ok and any("not in the approved contract" in r for r in rv.reasons), rv.reasons


def test_receipt_incomplete_coverage_rejected(tmp_path, contract):
    reqs = contract.get("requirements", [])
    if len(reqs) < 2:
        pytest.skip("fixture contract needs >=2 requirements to test partial coverage")
    repo = _git_init_candidate(tmp_path, ARM_B, contract)
    head = _git_head(repo)
    store = tmp_path / "store-partial"
    # A single VERIFIED check for ONE requirement must not satisfy the whole contract.
    one = [{"id": "check-x", "label": "x", "status": "VERIFIED", "detail": "", "requirementId": reqs[0]["id"]}]
    build_sentinel_store(store, repo, contract, head=head, checks_override=one)
    rv = verify_sentinel_receipt(store=store, approved_contract=_contract_file(tmp_path, contract),
                                 candidate_repo=repo, module_path=MODULE, expected_head=head)
    assert not rv.ok and any("no VERIFIED matching check" in r for r in rv.reasons), rv.reasons


# --------------------------------------------------------------------------- #
# P1 nonce reconciliation: trusted internal verifier, not a caller callback
# --------------------------------------------------------------------------- #
def _uncertain_store(tmp_path, roots):
    store = NonceStore(tmp_path / "recon.db", recon_verifier=ReconciliationVerifier(roots, policy_revision="1"))
    store.reserve(nonce="n-uncertain", pccb_id="pccb-1", effect_id="eff-1")
    return store


def test_reconciliation_valid_signed_evidence_resolves(tmp_path, trust):
    roots, kp = trust
    store = _uncertain_store(tmp_path, roots)
    ev = sign_reconciliation_statement(kp["reconciliation"], nonce="n-uncertain", pccb_id="pccb-1",
                                       effect_id="eff-1", resource_id="ledger-1", resolution="committed",
                                       outcome={"confirmed_by": "resource-readback"}, policy_revision="1")
    rec = store.reconcile(nonce="n-uncertain", resolution="committed", evidence=ev, resource_id="ledger-1")
    assert rec.state == "committed"


def test_reconciliation_forged_signer_rejected(tmp_path, trust):
    roots, kp = trust
    store = _uncertain_store(tmp_path, roots)
    rogue = KeyPair.generate("reconciliation", "rogue-recon-v1")  # NOT pinned in trust roots
    ev = sign_reconciliation_statement(rogue, nonce="n-uncertain", pccb_id="pccb-1", effect_id="eff-1",
                                       resource_id="ledger-1", resolution="committed", outcome={"x": 1})
    with pytest.raises(ReplayRefused) as ei:
        store.reconcile(nonce="n-uncertain", resolution="committed", evidence=ev, resource_id="ledger-1")
    assert ei.value.code == "RECONCILE_EVIDENCE_INVALID"
    assert store.get("n-uncertain").state == RESERVED  # stays uncertain (fail closed)


def test_reconciliation_wrong_effect_rejected(tmp_path, trust):
    roots, kp = trust
    store = _uncertain_store(tmp_path, roots)
    ev = sign_reconciliation_statement(kp["reconciliation"], nonce="n-uncertain", pccb_id="pccb-1",
                                       effect_id="DIFFERENT-effect", resource_id="ledger-1",
                                       resolution="committed", outcome={"x": 1})
    with pytest.raises(ReplayRefused) as ei:
        store.reconcile(nonce="n-uncertain", resolution="committed", evidence=ev, resource_id="ledger-1")
    assert ei.value.code == "RECONCILE_EVIDENCE_INVALID"
    assert store.get("n-uncertain").state == RESERVED


def test_reconciliation_no_callback_injection(tmp_path, trust):
    # reconcile() accepts NO caller callback; arbitrary/forged evidence cannot resolve an uncertain nonce.
    roots, kp = trust
    store = _uncertain_store(tmp_path, roots)
    forged = {"body": {"schema": "shipguard/reconciliation/v1", "nonce": "n-uncertain", "pccb_id": "pccb-1",
                       "effect_id": "eff-1", "resource_id": "ledger-1", "resolution": "committed",
                       "outcome": {}, "policy_revision": "1", "issued_at": "2099-01-01T00:00:00Z",
                       "reconciler": "x"},
              "key_id": kp["reconciliation"].key_id, "signature": "AAAAAAAAAAAAAAAA"}
    with pytest.raises(ReplayRefused):
        store.reconcile(nonce="n-uncertain", resolution="committed", evidence=forged, resource_id="ledger-1")
    assert store.get("n-uncertain").state == RESERVED


def test_reconciliation_unavailable_verifier_fails_closed(tmp_path, trust):
    roots, kp = trust
    store = NonceStore(tmp_path / "recon2.db")  # NO trusted verifier configured
    store.reserve(nonce="n2", pccb_id="p", effect_id="e")
    ev = sign_reconciliation_statement(kp["reconciliation"], nonce="n2", pccb_id="p", effect_id="e",
                                       resource_id="ledger-1", resolution="committed", outcome={"x": 1})
    with pytest.raises(ReplayRefused) as ei:
        store.reconcile(nonce="n2", resolution="committed", evidence=ev, resource_id="ledger-1")
    assert ei.value.code == "RECONCILE_UNAVAILABLE"
    assert store.get("n2").state == RESERVED


def test_cross_domain_signature_rejected(tmp_path, trust):
    # A signature minted for the correctness-cert domain must not verify under the reconciliation domain.
    roots, kp = trust
    body = {"x": 1}
    sig = sign_domain(kp["correctness"], DOMAIN_CORRECTNESS_CERT, body)
    assert verify_domain(kp["correctness"].public_key, DOMAIN_CORRECTNESS_CERT, body, sig) is True
    assert verify_domain(kp["correctness"].public_key, DOMAIN_RECONCILIATION, body, sig) is False

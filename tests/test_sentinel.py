"""Real Sentinel integration tests (mandate §THIRD).

Two layers:
  * Hermetic acceptance-logic tests over synthetic-but-faithful receipts (always run; they test
    the security-critical rule that a task is VERIFIED only when the contract identity, git
    identity, toolchain, mandatory ordinary tests, and full requirement coverage all qualify).
  * End-to-end tests that call the REAL `sentinel verify` (gated on the CLI being available;
    CI installs it so they cannot silently skip).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import actenon_shipguard as _sg
from actenon_shipguard.sentinel import (
    evaluate_receipt, find_sentinel, run_sentinel_verify, MANDATORY_TEST_CHECKS,
)

_PKG_DIR = Path(_sg.__file__).resolve().parent
FIXTURES = _PKG_DIR / "_bundled"
CONTRACT = json.loads((FIXTURES / "contracts" / "settlement-contract.json").read_text())
REQ_IDS = [r["id"] for r in CONTRACT["requirements"]]
MODULE = "src/settle.ts"


def _verified_receipt() -> dict:
    checks = [{"id": c, "status": "VERIFIED"} for c in MANDATORY_TEST_CHECKS]
    for rid in REQ_IDS:
        checks.append({"id": f"req:{rid}", "requirementId": rid, "status": "VERIFIED",
                       "label": rid, "args": [100, 4], "expected": [25, 25, 25, 25],
                       "observed": [25, 25, 25, 25]})
    return {
        "schemaVersion": 1, "status": "VERIFIED", "contract": CONTRACT,
        "contractHash": "c" * 64, "candidateHash": "d" * 64, "baselineHash": "e" * 64,
        "git": {"head": "a" * 40, "branch": "main", "dirty": True},
        "runner": "local-advisory",
        "runtime": {"node": "v26", "verifierVersion": "1.0.0", "vitest": "5.0.5", "workerSha256": "f" * 64},
        "checks": checks,
    }


# ----------------------------- hermetic acceptance logic ----------------------------- #
def test_fully_qualified_receipt_is_verified():
    v = evaluate_receipt(_verified_receipt(), CONTRACT)
    assert v.ok and v.status == "VERIFIED", v.reasons
    assert all(s == "VERIFIED" for s in v.requirements.values())


def test_contradicted_requirement_blocks_and_yields_counterexample():
    r = _verified_receipt()
    for c in r["checks"]:
        if c["id"] == "req:no-vanishing-penny":
            c.update(status="CONTRADICTED", args=[100, 3], expected=[34, 33, 33], observed=[33, 33, 33])
    r["status"] = "CONTRADICTED"
    v = evaluate_receipt(r, CONTRACT)
    assert not v.ok and v.status == "CONTRADICTED"
    assert v.counterexamples and v.counterexamples[0]["input"] == [100, 3]
    assert v.counterexamples[0]["observed"] == [33, 33, 33]


def test_status_verified_but_requirement_contradicted_is_rejected():
    # The top-level status lies; independent re-derivation must still refuse.
    r = _verified_receipt()
    for c in r["checks"]:
        if c["id"] == "req:no-created-penny":
            c.update(status="CONTRADICTED", args=[7, 2], expected=[4, 3], observed=[4, 4])
    v = evaluate_receipt(r, CONTRACT)          # status still "VERIFIED"
    assert not v.ok
    assert any("no-created-penny" in x for x in v.reasons)


def test_incomplete_requirement_coverage_is_rejected():
    r = _verified_receipt()
    r["checks"] = [c for c in r["checks"] if c["id"] != "req:preserve-formatting"]
    v = evaluate_receipt(r, CONTRACT)
    assert not v.ok
    assert any("no qualifying check" in x for x in v.reasons)


@pytest.mark.parametrize("cid", list(MANDATORY_TEST_CHECKS))
def test_failed_mandatory_ordinary_test_blocks(cid):
    r = _verified_receipt()
    for c in r["checks"]:
        if c["id"] == cid:
            c["status"] = "FAILED"
    v = evaluate_receipt(r, CONTRACT)
    assert not v.ok
    assert any(cid in x for x in v.reasons)


def test_substituted_contract_is_rejected():
    r = _verified_receipt()
    r["contract"] = {**CONTRACT, "objective": "a different, attacker-chosen objective"}
    v = evaluate_receipt(r, CONTRACT)
    assert not v.ok and any("contract" in x for x in v.reasons)


def test_short_git_head_is_rejected():
    r = _verified_receipt(); r["git"]["head"] = "abc123"
    v = evaluate_receipt(r, CONTRACT)
    assert not v.ok and any("40-char" in x for x in v.reasons)


def test_missing_verifier_identity_is_rejected():
    r = _verified_receipt(); r["runtime"].pop("verifierVersion")
    v = evaluate_receipt(r, CONTRACT)
    assert not v.ok and any("verifierVersion" in x for x in v.reasons)


def test_missing_candidate_binding_is_rejected():
    r = _verified_receipt(); r.pop("candidateHash")
    v = evaluate_receipt(r, CONTRACT)
    assert not v.ok and any("candidateHash" in x for x in v.reasons)


def test_unsupported_schema_is_rejected():
    r = _verified_receipt(); r["schemaVersion"] = 99
    v = evaluate_receipt(r, CONTRACT)
    assert not v.ok and any("schemaVersion" in x for x in v.reasons)


# ----------------------------- real CLI end-to-end (gated) ----------------------------- #
SENTINEL = find_sentinel()


def _resolve_node_modules():
    import os
    env = os.environ.get("SHIPGUARD_NODE_MODULES")
    cands = []
    if env:
        cands.append(Path(env))
    here = Path(__file__).resolve()
    cands += [here.parents[3] / "sentinel-verified" / "node_modules",
              here.parents[2] / "sentinel-verified" / "node_modules"]
    return next((p for p in cands if (p / ".bin" / "vitest").exists()), None)


NODE_MODULES = _resolve_node_modules()

pytestmark_cli = pytest.mark.skipif(
    SENTINEL is None or NODE_MODULES is None,
    reason="real sentinel CLI or node_modules(vitest) not available (set SHIPGUARD_SENTINEL / SHIPGUARD_NODE_MODULES)",
)


def _make_repo(tmp_path: Path, candidate: Path) -> Path:
    import shutil
    import subprocess
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    shutil.copy(FIXTURES / "candidates" / "baseline-buggy.ts", repo / MODULE)
    shutil.copy(FIXTURES / "target-settlement" / "src" / "settle.test.ts", repo / "src" / "settle.test.ts")
    (repo / "package.json").write_text(json.dumps(
        {"name": "settlement", "private": True, "type": "module", "scripts": {"test": "vitest run"}}))
    (repo / ".gitignore").write_text("node_modules\n")
    (repo / "node_modules").symlink_to(NODE_MODULES, target_is_directory=True)
    for a in (["init", "-q"], ["config", "user.email", "sg@x.local"], ["config", "user.name", "sg"],
              ["add", "-A"], ["commit", "-qm", "baseline"]):
        subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True)
    import shutil as _sh
    _sh.copy(candidate, repo / MODULE)        # the candidate change (uncommitted) vs baseline HEAD
    # Umask-independence (orchestrator.sync_file_modes_to_index): under umask 002 the scaffold
    # files carry 0664 bits and every file becomes a mode-only "change" for the snapshot diff.
    from actenon_shipguard.orchestrator import sync_file_modes_to_index
    sync_file_modes_to_index(repo)
    return repo


@pytest.mark.sentinel_integration
@pytestmark_cli
def test_real_sentinel_contradicts_wrong_fix(tmp_path):
    import shutil
    repo = _make_repo(tmp_path, FIXTURES / "candidates" / "arm-a-rounding.ts")
    contract = tmp_path / "acceptance.json"
    contract.write_text(json.dumps(CONTRACT))
    v = run_sentinel_verify(repo=repo, contract_path=contract, store=tmp_path / "store",
                            sentinel=SENTINEL, runner="local")
    assert v.status == "CONTRADICTED" and not v.ok, v.reasons
    assert v.ordinary_tests.get("candidate-tests") == "VERIFIED"     # the aspirin: green tests, real defect
    assert any(c["input"] == [100, 3] for c in v.counterexamples)
    assert v.receipt_hash and Path(v.report_path).exists()


@pytest.mark.sentinel_integration
@pytestmark_cli
def test_real_sentinel_verifies_correct_fix(tmp_path):
    repo = _make_repo(tmp_path, FIXTURES / "candidates" / "arm-b-correct.ts")
    contract = tmp_path / "acceptance.json"
    contract.write_text(json.dumps(CONTRACT))
    v = run_sentinel_verify(repo=repo, contract_path=contract, store=tmp_path / "store",
                            sentinel=SENTINEL, runner="local")
    assert v.ok and v.status == "VERIFIED", v.reasons
    assert all(s == "VERIFIED" for s in v.requirements.values())
    assert v.bindings.get("verifier_version") and len(v.bindings.get("git_head") or "") == 40
    # Phase 1.2/1.4: the evidence is content-addressed and bound to the exact candidate bytes.
    assert v.integrity.get("receipt_content_address_ok") is True
    assert v.integrity.get("referenced_objects_ok") is True
    assert v.integrity.get("fresh_receipt") is True
    assert v.integrity["candidate_identity"]["files_mismatched"] == []
    assert v.integrity["candidate_identity"]["files_hash_matched"], "candidate files must be hash-verified"


@pytest.mark.sentinel_integration
@pytestmark_cli
def test_offline_repair_loop_end_to_end_with_real_sentinel(tmp_path):
    """The full loop: a wrong change is CONTRADICTED by real Sentinel, the counterexample drives a
    repair, and the repaired candidate is independently re-verified — decided by Sentinel, not the agent."""
    from actenon_shipguard.adapters.offline import OfflineAdapter
    from actenon_shipguard.orchestrator import run_task

    rec = run_task(task="Conserve every penny when splitting a whole-pence total across N parties.",
                   adapter=OfflineAdapter(), work=tmp_path / "work", sentinel_cli=SENTINEL,
                   node_modules=NODE_MODULES, max_attempts=1, runner="local",
                   evidence_dir=tmp_path / "evidence")
    assert rec.final_status == "verified", rec.states
    assert rec.ordinary_tests_green_on_defect is True          # the aspirin
    verdicts = [a["challenge"]["verdict"] for a in rec.attempts]
    assert verdicts[0] == "CONTRADICTED" and verdicts[-1] == "VERIFIED"
    assert "COUNTEREXAMPLE" in rec.states and "ATTESTATION_READY" in rec.states
    assert rec.attempts[0]["challenge"]["counterexample"]["input"] == [100, 3]

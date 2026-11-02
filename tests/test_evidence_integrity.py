"""Evidence-integrity tests (Phase 1 of the v0.2.0 acceptance mandate).

Covers: CI failure propagation (1.1), stale-receipt reuse and content-addressing (1.2), Sentinel
status correctness against the real schema (1.3), committed-tree binding (1.4), agent change scope
(1.5) and ASPIRIN classification accuracy (1.7).

The status vocabulary asserted here is Sentinel's actual type (sentinel-verified @ becba502,
src/types.ts): 'VERIFIED' | 'CONTRADICTED' | 'UNVERIFIED' | 'REVIEW REQUIRED' | 'ENVIRONMENT FAILURE'.
"""
from __future__ import annotations

import hashlib
import json
import shlex
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

import actenon_shipguard as _sg
from actenon_shipguard.orchestrator import is_detected_defect, validate_change_scope
from actenon_shipguard.sentinel import (
    ACCEPT_STATUS,
    MANDATORY_TEST_CHECKS,
    SUPPORTED_RUNNERS,
    SUPPORTED_STATUSES,
    bind_committed_tree,
    evaluate_receipt,
    find_sentinel,
    run_sentinel_verify,
)

_PKG_DIR = Path(_sg.__file__).resolve().parent
FIXTURES = _PKG_DIR / "_bundled"
CONTRACT = json.loads((FIXTURES / "contracts" / "settlement-contract.json").read_text())
REQ_IDS = [r["id"] for r in CONTRACT["requirements"]]
MODULE = "src/settle.ts"
SETTLE_BYTES = (FIXTURES / "candidates" / "arm-b-correct.ts").read_bytes()
HEAD40 = "a" * 40
# The candidate tree Sentinel snapshots, and the tree that must still be on disk afterwards.
STANDARD_FILES = {MODULE: SETTLE_BYTES,
                  "src/settle.test.ts": b"// tests\n",
                  "package.json": b'{"name":"x"}\n',
                  ".gitignore": b"node_modules\n"}


# --------------------------------------------------------------------------- #
# Builders: a faithful content-addressed store, the way Sentinel writes it
# --------------------------------------------------------------------------- #
def _put(store: Path, payload: bytes) -> str:
    (store / "objects").mkdir(parents=True, exist_ok=True)
    h = hashlib.sha256(payload).hexdigest()
    (store / "objects" / h).write_bytes(payload)
    return h


def _snapshot(files: dict[str, bytes], head: str) -> bytes:
    snap = {"schemaVersion": 1,
            "files": {p: {"hash": hashlib.sha256(b).hexdigest(), "size": len(b), "mode": 420}
                      for p, b in files.items()},
            "git": {"root": "<work>/repo", "head": head, "branch": "main", "dirty": True}}
    return json.dumps(snap, separators=(",", ":")).encode()


def _checks(status: str = "VERIFIED", *, drop: str | None = None, duplicate: bool = False) -> list[dict]:
    out = [{"id": c, "label": c, "status": status, "detail": ""} for c in MANDATORY_TEST_CHECKS]
    for rid in REQ_IDS:
        out.append({"id": f"req:{rid}", "label": rid, "status": status, "detail": "",
                    "requirementId": rid, "args": [100, 4], "expected": [25, 25, 25, 25],
                    "observed": [25, 25, 25, 25]})
    if duplicate:
        out.append({"id": "candidate-tests", "label": "substituted", "status": "VERIFIED", "detail": ""})
    if drop:
        out = [c for c in out if c["id"] != drop]
    return out


def _receipt(status: str = "VERIFIED", **kw) -> dict:
    r = {"schemaVersion": 1, "id": "rcpt", "createdAt": "2026-11-02T00:00:00Z",
         "objective": CONTRACT["objective"], "baselineHash": "", "candidateHash": "",
         "contractHash": "", "git": {"root": "<work>/repo", "head": HEAD40, "branch": "main",
                                     "dirty": True},
         "runner": "local-advisory", "contract": CONTRACT, "checks": _checks(),
         "changes": [{"path": MODULE, "kind": "modified", "classification": "VERIFIED",
                      "reason": "Path authorised by the supplied contract"}],
         "status": status, "durationMs": 100,
         "runtime": {"node": "v22", "verifierVersion": "1.0.0", "vitest": "5.0.5",
                     "workerSha256": "f" * 64},
         "limitations": [], "nextActions": []}
    r.update(kw)
    return r


def _store(tmp_path: Path, receipt: dict, *, files: dict[str, bytes] | None = None,
           corrupt_receipt: bool = False, omit: tuple[str, ...] = ()) -> tuple[Path, str, dict]:
    """Write a content-addressed store consistent with `receipt`.

    Returns (store, receipt_key, completed_receipt) where completed_receipt carries the real
    baseline/candidate/contract object keys, exactly as Sentinel would have written them.
    """
    store = tmp_path / "store"
    files = STANDARD_FILES if files is None else files
    base_h = _put(store, _snapshot(files, HEAD40))
    cand_h = _put(store, _snapshot(files, HEAD40))
    con_h = _put(store, json.dumps(receipt["contract"], separators=(",", ":")).encode())
    r = dict(receipt, baselineHash=base_h, candidateHash=cand_h, contractHash=con_h)
    raw = json.dumps(r, separators=(",", ":")).encode()
    key = hashlib.sha256(raw).hexdigest()
    (store / "objects" / key).write_bytes(raw if not corrupt_receipt else raw + b" ")
    for k in omit:                                   # simulate a missing referenced object
        h = r.get(k)
        if h:
            (store / "objects" / h).unlink(missing_ok=True)
    (store / "latest-verification.json").write_text(
        json.dumps({"schemaVersion": 1, "receipt": key, "report": ""}))
    return store, key, r


def _repo_with(tmp_path: Path, files: dict[str, bytes] | None = None) -> Path:
    files = STANDARD_FILES if files is None else files
    repo = tmp_path / "repo"
    for rel, b in files.items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b)
    return repo


def _ev(tmp_path, receipt, **kw):
    """Build a faithful store for `receipt` and evaluate the receipt that was actually stored.

    ``files`` are the bytes the snapshot RECORDS; ``repo_files`` are the bytes actually ON DISK.
    They differ only where a test simulates a post-verification file swap.
    """
    store_keys = ("files", "corrupt_receipt", "omit")
    store, key, stored = _store(tmp_path, receipt, **{k: v for k, v in kw.items() if k in store_keys})
    repo = _repo_with(tmp_path, kw.get("repo_files"))
    return evaluate_receipt(stored, CONTRACT, receipt_hash=key, store=store, repo=repo,
                            exit_code=kw.get("exit_code", 0), attempt_id=kw.get("attempt_id", "a0"),
                            pointer_before=kw.get("pointer_before"))


# --------------------------------------------------------------------------- #
# 1.3 — status vocabulary is Sentinel's real schema, not ad hoc strings
# --------------------------------------------------------------------------- #
def test_status_vocabulary_matches_sentinel_exactly():
    assert SUPPORTED_STATUSES == {"VERIFIED", "CONTRADICTED", "UNVERIFIED",
                                 "REVIEW REQUIRED", "ENVIRONMENT FAILURE"}
    assert ACCEPT_STATUS == "VERIFIED"
    assert SUPPORTED_RUNNERS == {"local-advisory", "container-isolated"}


def test_fully_qualified_receipt_is_accepted(tmp_path):
    v = _ev(tmp_path, _receipt("VERIFIED"))
    assert v.ok and v.status == "VERIFIED", v.reasons
    assert v.integrity["receipt_content_address_ok"] is True
    assert v.integrity["referenced_objects_ok"] is True
    assert v.integrity["candidate_identity"]["files_mismatched"] == []


@pytest.mark.parametrize("status", ["CONTRADICTED", "UNVERIFIED", "REVIEW REQUIRED",
                                    "ENVIRONMENT FAILURE"])
def test_every_supported_non_verified_status_is_rejected(tmp_path, status):
    v = _ev(tmp_path, _receipt(status))
    assert not v.ok and v.status == status, (status, v.reasons)


def test_review_required_spelling_is_understood(tmp_path):
    """The pinned verifier emits 'REVIEW REQUIRED' with a SPACE; an underscore form is unknown."""
    v = _ev(tmp_path, _receipt("REVIEW REQUIRED"))
    assert not v.ok and any("UNRESOLVED_REVIEW" in r for r in v.reasons)


@pytest.mark.parametrize("bogus", ["REVIEW_REQUIRED", "ENVIRONMENT_FAILURE", "UNKNOWN", "FAILED",
                                   "PASSED", "VERIFIED ", "verified", ""])
def test_unknown_status_is_never_interpreted_as_acceptance(tmp_path, bogus):
    v = _ev(tmp_path, _receipt(bogus))
    assert not v.ok, f"{bogus!r} must not be accepted"
    assert any("UNKNOWN_STATUS" in r for r in v.reasons), v.reasons


def test_status_verified_but_a_requirement_contradicted_is_rejected(tmp_path):
    r = _receipt("VERIFIED")
    for c in r["checks"]:
        if c["id"] == "req:no-created-penny":
            c.update(status="CONTRADICTED", args=[7, 2], expected=[4, 3], observed=[4, 4])
    v = _ev(tmp_path, r)
    assert not v.ok and any("no-created-penny" in x for x in v.reasons)
    assert v.counterexamples and v.counterexamples[0]["input"] == [7, 2]


def test_duplicate_check_ids_are_rejected(tmp_path):
    v = _ev(tmp_path, _receipt("VERIFIED", checks=_checks(duplicate=True)))
    assert not v.ok and any("DUPLICATE_CHECK_IDS" in r for r in v.reasons)


@pytest.mark.parametrize("cid", list(MANDATORY_TEST_CHECKS))
def test_missing_mandatory_check_is_rejected(tmp_path, cid):
    v = _ev(tmp_path, _receipt("VERIFIED", checks=_checks(drop=cid)))
    assert not v.ok and any("MISSING_MANDATORY_CHECK" in r and cid in r for r in v.reasons)


def test_empty_check_set_is_rejected(tmp_path):
    v = _ev(tmp_path, _receipt("VERIFIED", checks=[]))
    assert not v.ok and any("EMPTY_CHECK_SET" in r for r in v.reasons)


def test_incomplete_requirement_coverage_is_rejected(tmp_path):
    r = _receipt("VERIFIED")
    r["checks"] = [c for c in r["checks"] if c["id"] != "req:preserve-formatting"]
    v = _ev(tmp_path, r)
    assert not v.ok and any("INCOMPLETE_COVERAGE" in r2 for r2 in v.reasons)


# --------------------------------------------------------------------------- #
# 1.2 — freshness, content-addressing, referenced objects, candidate identity
# --------------------------------------------------------------------------- #
def test_unchanged_store_pointer_is_stale_receipt_reuse(tmp_path):
    store, key, stored = _store(tmp_path, _receipt("VERIFIED"))
    v = evaluate_receipt(stored, CONTRACT, receipt_hash=key, store=store,
                         repo=_repo_with(tmp_path), exit_code=0, attempt_id="a1",
                         pointer_before=key)
    assert not v.ok and any("STALE_RECEIPT_REUSE" in r for r in v.reasons)


def test_changed_store_pointer_is_fresh_evidence(tmp_path):
    store, key, stored = _store(tmp_path, _receipt("VERIFIED"))
    v = evaluate_receipt(stored, CONTRACT, receipt_hash=key, store=store,
                         repo=_repo_with(tmp_path), exit_code=0, attempt_id="a1",
                         pointer_before="b" * 64)
    assert v.ok, v.reasons
    assert v.integrity["fresh_receipt"] is True


def test_receipt_content_address_mismatch_is_rejected(tmp_path):
    r = _receipt("VERIFIED")
    v = _ev(tmp_path, r, corrupt_receipt=True)
    assert not v.ok and any("content-address" in x for x in v.reasons)


@pytest.mark.parametrize("obj", ["baselineHash", "candidateHash", "contractHash"])
def test_missing_referenced_object_is_rejected(tmp_path, obj):
    v = _ev(tmp_path, _receipt("VERIFIED"), omit=(obj,))
    assert not v.ok and any("missing from the store" in x for x in v.reasons)


def test_candidate_bytes_differing_from_the_snapshot_are_rejected(tmp_path):
    """The evidence must bind the EXACT bytes checked: swap the file after snapshotting."""
    swapped = dict(STANDARD_FILES)
    swapped[MODULE] = b"export function allocate(){ return [0]; }\n"
    v = _ev(tmp_path, _receipt("VERIFIED"), repo_files=swapped)
    assert not v.ok and any("candidate bytes differ" in x for x in v.reasons)


def test_candidate_file_deleted_after_verification_is_rejected(tmp_path):
    gone = dict(STANDARD_FILES)
    gone.pop(MODULE)
    v = _ev(tmp_path, _receipt("VERIFIED"), repo_files=gone)
    assert not v.ok and any("absent from the worktree" in x for x in v.reasons)


def test_substituted_contract_is_rejected(tmp_path):
    r = _receipt("VERIFIED")
    v = evaluate_receipt(r, {**CONTRACT, "objective": "attacker objective"},
                         receipt_hash="c" * 64, exit_code=0)
    assert not v.ok and any("approved contract" in x for x in v.reasons)


def test_short_git_head_is_rejected(tmp_path):
    r = _receipt("VERIFIED"); r["git"]["head"] = "abc123"
    v = _ev(tmp_path, r)
    assert not v.ok and any("40-char" in x for x in v.reasons)


@pytest.mark.parametrize("exit_code,status", [(0, "CONTRADICTED"), (1, "VERIFIED"), (2, "VERIFIED")])
def test_exit_status_inconsistency_is_rejected(tmp_path, exit_code, status):
    v = _ev(tmp_path, _receipt(status), exit_code=exit_code)
    assert not v.ok
    assert any("INCONSISTENT_VERDICT" in x or "exited 2" in x for x in v.reasons), v.reasons


def test_consistent_exit_and_status_is_accepted(tmp_path):
    assert _ev(tmp_path, _receipt("VERIFIED"), exit_code=0).ok
    v = _ev(tmp_path, _receipt("CONTRADICTED"), exit_code=1)
    assert not v.ok and v.status == "CONTRADICTED"


# --------------------------------------------------------------------------- #
# 1.5 — change scope is validated, not assumed from the prompt
# --------------------------------------------------------------------------- #
def test_out_of_scope_change_is_rejected(tmp_path):
    r = _receipt("VERIFIED")
    r["changes"].append({"path": "src/other.ts", "kind": "added", "classification": "VERIFIED",
                         "reason": "x"})
    v = _ev(tmp_path, r)
    assert not v.ok and any("OUT_OF_SCOPE_CHANGES" in x for x in v.reasons)


def test_test_file_modification_requires_review(tmp_path):
    r = _receipt("VERIFIED")
    r["changes"].append({"path": "src/settle.test.ts", "kind": "modified",
                         "classification": "VERIFIED", "reason": "x"})
    v = _ev(tmp_path, r)
    assert not v.ok and any("TEST_MODIFICATION_REQUIRES_REVIEW" in x for x in v.reasons)


def test_dependency_change_requires_review(tmp_path):
    r = _receipt("VERIFIED")
    r["changes"].append({"path": "package.json", "kind": "modified",
                         "classification": "VERIFIED", "reason": "x"})
    v = _ev(tmp_path, r)
    assert not v.ok and any("DEPENDENCY_CHANGE_REQUIRES_REVIEW" in x for x in v.reasons)


def test_unauthorised_change_classification_is_rejected(tmp_path):
    r = _receipt("VERIFIED")
    r["changes"] = [{"path": MODULE, "kind": "modified", "classification": "REVIEW REQUIRED",
                     "reason": "not authorised"}]
    v = _ev(tmp_path, r)
    assert not v.ok and any("UNAUTHORISED_CHANGE_CLASSIFICATION" in x for x in v.reasons)


def test_validate_change_scope_flags_real_diff(tmp_path):
    repo = _repo_with(tmp_path)
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.email=a@b.c", "-c", "user.name=t",
                    "commit", "-qm", "base"], check=True)
    (repo / MODULE).write_bytes(SETTLE_BYTES + b"// edited\n")
    s = validate_change_scope(repo, [MODULE])
    assert s["clean"] is True and s["in_scope"] == [MODULE]
    # now the agent weakens a test instead of fixing the code
    (repo / "src" / "settle.test.ts").write_bytes(b"// deleted all assertions\n")
    s2 = validate_change_scope(repo, [MODULE])
    assert s2["clean"] is False and s2["test_changes"] == ["src/settle.test.ts"]
    assert s2["out_of_scope"] == ["src/settle.test.ts"]


# --------------------------------------------------------------------------- #
# 1.7 — ASPIRIN classification accuracy
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("passed,verdict,ok,expected", [
    (True, "CONTRADICTED", False, True),        # the only genuine aspirin case
    (True, "VERIFIED", True, False),            # nothing wrong to detect
    (False, "CONTRADICTED", False, False),      # ordinary tests already failed
    (None, "CONTRADICTED", False, False),       # tests did not run
    (True, "ENVIRONMENT FAILURE", False, False),
    (True, "REVIEW REQUIRED", False, False),
    (True, "UNVERIFIED", False, False),
    (True, "UNKNOWN_STATUS", False, False),
    (True, "CONTRADICTED", True, False),        # inconsistent: cannot be a detected defect
])
def test_aspirin_only_for_a_real_contradiction(passed, verdict, ok, expected):
    assert is_detected_defect(passed, {"verdict": verdict, "ok": ok}) is expected


# --------------------------------------------------------------------------- #
# 1.1 — CI failure propagation, with a real negative control
# --------------------------------------------------------------------------- #
CI_YAML = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "ci.yml"


def test_ci_uses_bash_pipefail_and_checks_pytest_exit_code():
    doc = yaml.safe_load(CI_YAML.read_text())
    assert doc.get("defaults", {}).get("run", {}).get("shell") == "bash", \
        "workflow must default run steps to bash so pipefail applies"
    steps = [s for j in doc["jobs"].values() for s in j.get("steps", []) if isinstance(s.get("run"), str)]
    pytest_steps = [s for s in steps if "pytest" in s["run"]]
    assert pytest_steps, "expected mandatory pytest steps in CI"
    for s in pytest_steps:
        run = s["run"]
        assert "set -euo pipefail" in run, f"step {s.get('name')!r} lacks pipefail"
        assert "PIPESTATUS[0]" in run, f"step {s.get('name')!r} does not assert pytest's exit code"


def test_negative_control_failing_pytest_cannot_be_masked_by_tee(tmp_path):
    """A failing test among passing ones must fail the step; the old un-piped pattern hid it."""
    (tmp_path / "test_mixed.py").write_text(
        "def test_passes():\n    assert True\n\ndef test_fails():\n    assert False\n")
    py = shlex.quote(sys.executable)          # a bare `python` may not exist on PATH at all
    # The pre-fix CI pattern: `pytest | tee` under bash -e (no pipefail) -> tee's 0 masks pytest.
    old = subprocess.run(["bash", "-e", "-c",
                          f"{py} -m pytest -q -p no:cacheprovider {tmp_path} 2>&1 | tee /tmp/_old.txt"],
                         capture_output=True, text=True)
    assert "1 failed" in old.stdout, f"the negative control did not actually run pytest: {old.stdout[-400:]}"
    assert old.returncode == 0, "sanity: without pipefail the failure IS masked (the bug being fixed)"
    # The hardened pattern now used in ci.yml.
    new = subprocess.run(
        ["bash", "-c",
         f'set -euo pipefail; set +e; {py} -m pytest -q -p no:cacheprovider {tmp_path} 2>&1 '
         '| tee /tmp/_new.txt; code=${PIPESTATUS[0]}; set -e; test "$code" -eq 0'],
        capture_output=True, text=True)
    assert new.returncode != 0, "a failing pytest must fail the CI step even though another test passed"


def test_negative_control_pipefail_semantics():
    masked = subprocess.run(["bash", "-c", "false | tee /dev/null"], capture_output=True)
    assert masked.returncode == 0
    strict = subprocess.run(["bash", "-eo", "pipefail", "-c", "false | tee /dev/null"],
                            capture_output=True)
    assert strict.returncode != 0


# --------------------------------------------------------------------------- #
# 1.2 / 1.4 — real CLI: stale receipt regression and committed-tree binding
# --------------------------------------------------------------------------- #
SENTINEL = find_sentinel()


def _resolve_nm():
    import os
    env = os.environ.get("SHIPGUARD_NODE_MODULES")
    cands = ([Path(env)] if env else []) + [
        Path(__file__).resolve().parents[3] / "sentinel-verified" / "node_modules",
        Path(__file__).resolve().parents[2] / "sentinel-verified" / "node_modules"]
    return next((p for p in cands if (p / ".bin" / "vitest").exists()), None)


NODE_MODULES = _resolve_nm()
needs_sentinel = pytest.mark.skipif(SENTINEL is None or NODE_MODULES is None,
                                    reason="real sentinel CLI or node_modules(vitest) unavailable")


def _candidate_repo(tmp_path: Path, candidate: Path) -> Path:
    import shutil
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
    import shutil as sh
    sh.copy(candidate, repo / MODULE)
    # Umask-independence (see orchestrator.sync_file_modes_to_index): a shutil.copy under
    # umask 002 carries 0664 bits that make every file a mode-only "change" for the snapshot diff.
    from actenon_shipguard.orchestrator import sync_file_modes_to_index
    sync_file_modes_to_index(repo)
    return repo


@pytest.mark.sentinel_integration
@needs_sentinel
def test_stale_verified_receipt_is_not_reused_when_a_later_attempt_fails(tmp_path, monkeypatch):
    """Mandate regression: attempt 1 is VERIFIED; attempt 2 fails WITHOUT updating the pointer, so
    the earlier VERIFIED receipt must never be accepted as attempt 2's evidence."""
    import actenon_shipguard.sentinel as S
    repo = _candidate_repo(tmp_path, FIXTURES / "candidates" / "arm-b-correct.ts")
    contract = tmp_path / "acceptance.json"
    contract.write_text(json.dumps(CONTRACT))
    store = tmp_path / "store"

    v1 = S.run_sentinel_verify(repo=repo, contract_path=contract, store=store, sentinel=SENTINEL,
                               runner="local", fresh_store=False, attempt_id="a1")
    assert v1.ok and v1.status == "VERIFIED", v1.reasons
    stale_pointer = (store / "latest-verification.json").read_text()
    stale_hash = json.loads(stale_pointer)["receipt"]

    # Attempt 2: the candidate is now WRONG, and the invocation dies before recording evidence.
    import shutil
    shutil.copy(FIXTURES / "candidates" / "arm-a-rounding.ts", repo / MODULE)

    def _interrupted(cmd, **kw):
        raise S.subprocess.TimeoutExpired(cmd=cmd, timeout=1)

    monkeypatch.setattr(S.subprocess, "run", _interrupted)
    v2 = S.run_sentinel_verify(repo=repo, contract_path=contract, store=store, sentinel=SENTINEL,
                               runner="local", fresh_store=False, attempt_id="a2")
    assert not v2.ok and v2.status == "ENVIRONMENT_FAILURE", v2

    # The pointer still advertises the earlier VERIFIED receipt; re-presenting it must be refused.
    assert json.loads((store / "latest-verification.json").read_text())["receipt"] == stale_hash
    receipt = json.loads((store / "objects" / stale_hash).read_bytes())
    v3 = S.evaluate_receipt(receipt, CONTRACT, receipt_hash=stale_hash, store=store, repo=repo,
                            exit_code=0, attempt_id="a2", pointer_before=stale_hash)
    assert not v3.ok
    assert any("STALE_RECEIPT_REUSE" in r for r in v3.reasons), v3.reasons


@pytest.mark.sentinel_integration
@needs_sentinel
def test_committed_tree_is_provably_identical_to_the_verified_candidate(tmp_path):
    """Phase 1.4: a receipt records the HEAD at verification time; the committed candidate must be
    independently bound to the exact bytes Sentinel checked."""
    repo = _candidate_repo(tmp_path, FIXTURES / "candidates" / "arm-b-correct.ts")
    contract = tmp_path / "acceptance.json"
    contract.write_text(json.dumps(CONTRACT))
    store = tmp_path / "store"
    v = run_sentinel_verify(repo=repo, contract_path=contract, store=store, sentinel=SENTINEL,
                            runner="local", attempt_id="a1")
    assert v.ok, v.reasons
    attempt_store = store / "attempt-a1"
    for a in (["add", "--", MODULE], ["commit", "-qm", "verified change"]):
        subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True)
    commit = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                            capture_output=True, text=True, check=True).stdout.strip()
    b = bind_committed_tree(store=attempt_store, receipt_hash=v.receipt_hash, repo=repo, commit=commit)
    assert b["equivalent"] is True and b["files_checked"] >= 1 and not b["mismatches"], b

    # Negative control: a later commit that changes the file is NOT the verified candidate.
    (repo / MODULE).write_bytes(SETTLE_BYTES + b"// drifted after verification\n")
    subprocess.run(["git", "-C", str(repo), "add", "--", MODULE], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.email=a@b.c", "-c", "user.name=t",
                    "commit", "-qm", "drift"], check=True, capture_output=True)
    drifted = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                             capture_output=True, text=True, check=True).stdout.strip()
    b2 = bind_committed_tree(store=attempt_store, receipt_hash=v.receipt_hash, repo=repo, commit=drifted)
    assert b2["equivalent"] is False and b2["mismatches"], b2

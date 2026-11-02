"""Real Sentinel integration with evidence-integrity enforcement (mandate §THIRD, Phase 1).

Calls the *supported* Sentinel verifier (``sentinel verify``) and consumes the STRUCTURED receipt from
its content-addressed store — never a terminal string. Acceptance is independently re-derived here and
validated against Sentinel's actual schema (``sentinel-verified`` @ ``becba502``, ``src/types.ts``):

    Status = 'VERIFIED' | 'CONTRADICTED' | 'UNVERIFIED' | 'REVIEW REQUIRED' | 'ENVIRONMENT FAILURE'
    Receipt{schemaVersion:1|2, baselineHash, candidateHash, contractHash, git, runner, checks[], changes[], status, runtime}
    Snapshot{schemaVersion:1, files{path:{hash,size,mode}}, git}

Integrity guarantees enforced (Phase 1.2/1.3/1.4/1.6):
  * FRESH EVIDENCE PER ATTEMPT — the store pointer must change; a failed/interrupted invocation can
    never fall back to an earlier VERIFIED receipt (STALE_RECEIPT_REUSE).
  * CONTENT-ADDRESS VERIFICATION — sha256(receipt bytes) == its object key, and the same for every
    referenced object (baseline / candidate / contract snapshots).
  * EXACT CANDIDATE IDENTITY — the recorded candidate Snapshot's per-file sha256 must equal the
    sha256 of the actual bytes on disk, so the evidence is bound to the code that was really checked.
  * SCHEMA-CORRECT STATUSES — only the five supported statuses are understood; an unknown status,
    duplicate check ids, a missing mandatory check, or an inconsistent top-level verdict are all
    non-acceptance. Exit-status consistency is required (0 <-> VERIFIED, 2 -> reject).
  * CHANGE SCOPE — every changed path must be authorised by the contract's ``allowedPaths`` and
    classified VERIFIED by Sentinel; test/dependency changes force human review.
  * PORTABLE DISCLOSURE — a relative-path-only summary suitable for publication. Raw receipts (which
    embed absolute local paths) stay in the local store for replay; bytes are never scrubbed and then
    presented as hash-preserving.

Honest limitation (Sentinel records it too): the ``local`` runner executes candidate code under the
same OS account and is advisory, not a security boundary. Use ``runner="docker"`` for isolation.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# --- Sentinel's actual supported vocabulary (src/types.ts @ becba502) --------------------- #
SUPPORTED_STATUSES = frozenset({
    "VERIFIED", "CONTRADICTED", "UNVERIFIED", "REVIEW REQUIRED", "ENVIRONMENT FAILURE",
})
ACCEPT_STATUS = "VERIFIED"
REVIEW_STATUS = "REVIEW REQUIRED"
SUPPORTED_RECEIPT_SCHEMA = frozenset({1, 2})
SUPPORTED_CONTRACT_SCHEMA = frozenset({1, 2, 3})
SUPPORTED_RUNNERS = frozenset({"local-advisory", "container-isolated"})
# Ordinary-test checks that must be present and VERIFIED before any acceptance.
MANDATORY_TEST_CHECKS = ("baseline-tests", "candidate-tests", "preserved-tests")
# Paths whose modification means the agent changed the rules, not the implementation.
_TEST_PATH_MARKERS = (".test.", ".spec.", "__tests__/", "/test/", "test/", "tests/")
_DEPENDENCY_PATHS = ("package.json", "package-lock.json", "npm-shrinkwrap.json", "yarn.lock",
                     "pnpm-lock.yaml", "node_modules")

# Exit codes documented by the Sentinel CLI.
EXIT_PASSED, EXIT_NOT_ACCEPTED, EXIT_USAGE = 0, 1, 2


def find_sentinel(explicit: str | None = None) -> list[str] | None:
    """Resolve the Sentinel CLI command prefix.

    Order: explicit path, ``$SHIPGUARD_SENTINEL``, ``sentinel`` on PATH, then the lab sibling repo's
    built ``dist/cli.js`` (run via node). Returns ``None`` when unavailable.
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


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha256_file(p: Path) -> str:
    return sha256_bytes(Path(p).read_bytes())


@dataclass
class SentinelVerdict:
    ok: bool                        # True ONLY on independently re-derived VERIFIED acceptance
    status: str                     # a supported Sentinel Status, or a ShipGuard integrity failure label
    reasons: list[str] = field(default_factory=list)
    counterexamples: list[dict] = field(default_factory=list)
    requirements: dict = field(default_factory=dict)     # requirement id -> check status
    ordinary_tests: dict = field(default_factory=dict)   # mandatory test check id -> status
    bindings: dict = field(default_factory=dict)         # hashes, git identity, toolchain, runner
    integrity: dict = field(default_factory=dict)        # content-address / freshness / scope results
    changes: list[dict] = field(default_factory=list)
    non_verified_checks: list[dict] = field(default_factory=list)
    duplicate_check_ids: list[str] = field(default_factory=list)
    receipt_hash: str = ""
    report_path: str = ""
    exit_code: int | None = None
    attempt_id: str = ""
    disclosure: dict = field(default_factory=dict)       # portable, relative-path-only, publishable
    raw: dict = field(default_factory=dict)              # local only; embeds absolute paths

    # Integrity failures are ShipGuard-side labels, deliberately NOT Sentinel statuses.
    def is_integrity_failure(self) -> bool:
        return self.status.startswith("EVIDENCE_") or self.status == "ENVIRONMENT_FAILURE"

    def to_dict(self, *, include_raw: bool = False) -> dict[str, Any]:
        d = {"ok": self.ok, "status": self.status, "reasons": self.reasons,
             "counterexamples": self.counterexamples, "requirements": self.requirements,
             "ordinary_tests": self.ordinary_tests, "bindings": self.bindings,
             "integrity": self.integrity, "changes": self.changes,
             "non_verified_checks": self.non_verified_checks,
             "duplicate_check_ids": self.duplicate_check_ids,
             "receipt_hash": self.receipt_hash,
             # Portable: only the basename is published; the absolute local path stays on the object.
             "report_basename": Path(self.report_path).name if self.report_path else "",
             "exit_code": self.exit_code, "attempt_id": self.attempt_id,
             "disclosure": self.disclosure}
        if include_raw:
            d["raw"] = self.raw
        return d


def _fail(status: str, reasons: list[str], **kw) -> SentinelVerdict:
    return SentinelVerdict(ok=False, status=status, reasons=reasons, **kw)


def _is_hex(s: Any, n: int) -> bool:
    return isinstance(s, str) and len(s) == n and all(c in "0123456789abcdef" for c in s)


def is_test_path(p: str) -> bool:
    return any(m in p for m in _TEST_PATH_MARKERS)


def is_dependency_path(p: str) -> bool:
    return any(p == d or p.endswith("/" + d) or p.startswith(d + "/") for d in _DEPENDENCY_PATHS)


def _counterexample(check: dict) -> dict:
    """Prefer Sentinel's shrunk minimal counterexample when the check carries one."""
    cx = check.get("counterexample") or {}
    minimal = cx.get("minimal")
    return {
        "requirement_id": check.get("requirementId") or check.get("id"),
        "check_id": check.get("id"),
        "label": check.get("label"),
        "input": minimal if minimal is not None else check.get("args"),
        "expected": check.get("expected"),
        "observed": check.get("observed"),
        "detail": check.get("detail"),
        "shrunk": bool(minimal is not None),
        "shrink_attempts": cx.get("attempts"),
        "guarantee": cx.get("guarantee"),
        "original_input": cx.get("original"),
    }


def _load_object(store: Path, key: str, label: str, problems: list[str]) -> Any | None:
    """Load a content-addressed object and VERIFY sha256(bytes) == key."""
    if not _is_hex(key, 64):
        problems.append(f"{label} is not a sha256 hex digest: {key!r}")
        return None
    p = store / "objects" / key
    if not p.exists():
        problems.append(f"{label} object {key[:12]}… is missing from the store")
        return None
    b = p.read_bytes()
    actual = sha256_bytes(b)
    if actual != key:
        problems.append(f"{label} object failed content-address check: key {key[:12]}… != sha256(bytes) {actual[:12]}…")
        return None
    try:
        return json.loads(b)
    except Exception as e:  # noqa: BLE001
        problems.append(f"{label} object {key[:12]}… is not valid JSON: {e}")
        return None


def _pointer(store: Path) -> str | None:
    lv = store / "latest-verification.json"
    if not lv.exists():
        return None
    try:
        return json.loads(lv.read_text()).get("receipt")
    except Exception:  # noqa: BLE001
        return None


def check_candidate_identity(repo: Path, snapshot: dict, problems: list[str]) -> dict:
    """Independently verify the recorded candidate Snapshot against the bytes actually on disk."""
    files = snapshot.get("files") or {}
    verified, mismatched, missing = [], [], []
    for rel, meta in files.items():
        rec = (meta or {}).get("hash")
        p = repo / rel
        if not p.exists():
            missing.append(rel)
            continue
        actual = sha256_file(p)
        if actual == rec:
            verified.append(rel)
        else:
            mismatched.append({"path": rel, "recorded": rec, "actual": actual})
    if missing:
        problems.append(f"candidate snapshot lists files absent from the worktree: {missing}")
    if mismatched:
        problems.append(f"candidate bytes differ from the verified snapshot: {mismatched}")
    return {"files_checked": len(files), "files_hash_matched": verified,
            "files_mismatched": mismatched, "files_missing": missing}


def bind_committed_tree(*, store: Path, receipt_hash: str, repo: Path, commit: str) -> dict:
    """Establish a CHECKABLE tree-equivalence binding between a commit and what Sentinel verified.

    A receipt records the git HEAD *at verification time* (usually the pre-change baseline with a
    dirty worktree). It does NOT by itself attest a later commit. This function closes that gap by
    comparing sha256 of each committed blob against the candidate Snapshot's recorded file hashes:
    if every file matches, the committed tree is byte-identical to the verified candidate.
    """
    out: dict[str, Any] = {"commit": commit, "receipt_hash": receipt_hash,
                           "candidate_hash": None, "files_checked": 0, "files_matched": [],
                           "mismatches": [], "equivalent": False, "method":
                           "sha256(git show <commit>:<path>) == candidateSnapshot.files[path].hash"}
    problems: list[str] = []
    snap_key = None
    rp = store / "objects" / receipt_hash
    if not rp.exists():
        out["error"] = f"receipt {receipt_hash[:12]}… not present in store"
        return out
    receipt = json.loads(rp.read_bytes())
    snap_key = receipt.get("candidateHash")
    out["candidate_hash"] = snap_key
    snapshot = _load_object(store, snap_key, "candidate-snapshot", problems) if snap_key else None
    if snapshot is None:
        out["error"] = "; ".join(problems) or "candidate snapshot unavailable"
        return out
    for rel, meta in (snapshot.get("files") or {}).items():
        rec = (meta or {}).get("hash")
        got = subprocess.run(["git", "-C", str(repo), "show", f"{commit}:{rel}"],
                             capture_output=True)
        if got.returncode != 0:
            out["mismatches"].append({"path": rel, "reason": f"not present in commit {commit[:12]}"})
            continue
        actual = sha256_bytes(got.stdout)
        if actual == rec:
            out["files_matched"].append(rel)
        else:
            out["mismatches"].append({"path": rel, "recorded": rec, "actual": actual})
        out["files_checked"] += 1
    out["equivalent"] = (out["files_checked"] > 0 and not out["mismatches"] and not problems)
    if problems:
        out["error"] = "; ".join(problems)
    return out


def evaluate_receipt(receipt: dict, approved_contract: dict, *, receipt_hash: str = "",
                     report_path: str = "", store: Path | None = None, repo: Path | None = None,
                     exit_code: int | None = None, attempt_id: str = "",
                     pointer_before: str | None = None,
                     require_fresh_pointer: bool = True) -> SentinelVerdict:
    """Independently re-derive acceptance from a structured Sentinel receipt.

    Never trusts the top-level ``status`` alone. Enforces schema, content-addressing, exact contract
    and candidate identity, mandatory checks, full requirement coverage, all-checks-VERIFIED,
    duplicate-check detection, exit-status consistency, pointer freshness and change scope.
    """
    reasons: list[str] = []
    integrity: dict[str, Any] = {}
    store = Path(store) if store else None

    # ---- 1. Fresh evidence for THIS attempt (never reuse an earlier receipt) -------------- #
    if require_fresh_pointer:
        if pointer_before is None:
            # No prior evidence in this store, so whatever we read was produced by this attempt.
            fresh = True
        else:
            fresh = bool(receipt_hash) and receipt_hash != pointer_before
        integrity["pointer_before"] = pointer_before
        integrity["pointer_after"] = receipt_hash
        integrity["fresh_receipt"] = fresh
        if not fresh:
            reasons.append(f"STALE_RECEIPT_REUSE: store pointer unchanged ({str(pointer_before)[:12]}…); "
                           "this attempt produced no new verification evidence")

    # ---- 2. Content-address verification of the receipt and referenced objects ------------ #
    if store is not None and receipt_hash:
        rp = store / "objects" / receipt_hash
        if not rp.exists():
            reasons.append(f"receipt object {receipt_hash[:12]}… is absent from the store")
        else:
            actual = sha256_bytes(rp.read_bytes())
            integrity["receipt_content_address_ok"] = (actual == receipt_hash)
            if actual != receipt_hash:
                reasons.append(f"receipt failed content-address check: key {receipt_hash[:12]}… "
                               f"!= sha256(bytes) {actual[:12]}…")
        obj_problems: list[str] = []
        baseline_snap = _load_object(store, receipt.get("baselineHash") or "", "baseline-snapshot", obj_problems)
        candidate_snap = _load_object(store, receipt.get("candidateHash") or "", "candidate-snapshot", obj_problems)
        contract_obj = _load_object(store, receipt.get("contractHash") or "", "contract", obj_problems) \
            if receipt.get("contractHash") else None
        integrity["referenced_objects_ok"] = not obj_problems
        reasons.extend(obj_problems)
    else:
        baseline_snap = candidate_snap = contract_obj = None

    # ---- 3. Schema / vocabulary correctness --------------------------------------------- #
    sv = receipt.get("schemaVersion")
    if sv not in SUPPORTED_RECEIPT_SCHEMA:
        reasons.append(f"unsupported receipt schemaVersion={sv!r} (supported: {sorted(SUPPORTED_RECEIPT_SCHEMA)})")
    status = receipt.get("status")
    if status not in SUPPORTED_STATUSES:
        reasons.append(f"UNKNOWN_STATUS {status!r} — not one of Sentinel's supported statuses "
                       f"{sorted(SUPPORTED_STATUSES)}; refusing to interpret it as acceptance")
    runner = receipt.get("runner")
    if runner not in SUPPORTED_RUNNERS:
        reasons.append(f"unsupported runner {runner!r} (supported: {sorted(SUPPORTED_RUNNERS)})")
    rt = receipt.get("runtime") or {}
    if not rt.get("verifierVersion"):
        reasons.append("receipt runtime.verifierVersion missing (verifier identity unbound)")

    # ---- 4. Git identity ------------------------------------------------------------------- #
    git = receipt.get("git") or {}
    if not _is_hex(git.get("head"), 40):
        reasons.append(f"receipt git.head is not a full 40-char commit sha: {git.get('head')!r}")
    if not receipt.get("candidateHash"):
        reasons.append("receipt has no candidateHash (candidate source not bound)")

    # ---- 5. Exact approved-contract identity ----------------------------------------------- #
    csv = (approved_contract or {}).get("schemaVersion")
    if csv not in SUPPORTED_CONTRACT_SCHEMA:
        reasons.append(f"approved contract schemaVersion={csv!r} not supported by this integration")
    if receipt.get("contract") != approved_contract:
        reasons.append("receipt contract does not deep-equal the approved contract (wrong/substituted contract)")
    if contract_obj is not None and contract_obj != approved_contract:
        reasons.append("stored contract object does not deep-equal the approved contract")
    if not receipt.get("contractHash"):
        reasons.append("receipt has no contractHash (no approved contract was bound)")

    # ---- 6. Exact candidate identity (snapshot file hashes vs real bytes) ------------------- #
    if candidate_snap is not None and repo is not None:
        cand = check_candidate_identity(Path(repo), candidate_snap, reasons)
        integrity["candidate_identity"] = cand
        snap_git = (candidate_snap.get("git") or {}).get("head")
        integrity["snapshot_git_head_matches_receipt"] = (snap_git == git.get("head"))
        if snap_git != git.get("head"):
            reasons.append(f"candidate snapshot git head {str(snap_git)[:12]}… != receipt git head "
                           f"{str(git.get('head'))[:12]}…")

    # ---- 7. Checks: duplicates, mandatory presence, coverage, all-VERIFIED ------------------- #
    checks = receipt.get("checks") or []
    ids = [c.get("id") for c in checks if isinstance(c, dict)]
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    if dupes:
        reasons.append(f"DUPLICATE_CHECK_IDS: {dupes} (substituted or replayed check set)")
    by_id: dict[str, dict] = {}
    for c in checks:
        if isinstance(c, dict) and c.get("id") not in by_id:
            by_id[c.get("id")] = c

    ordinary: dict[str, str] = {}
    for cid in MANDATORY_TEST_CHECKS:
        c = by_id.get(cid)
        st = (c or {}).get("status", "MISSING")
        ordinary[cid] = st
        if c is None:
            reasons.append(f"MISSING_MANDATORY_CHECK: {cid!r} was not executed")
        elif st != ACCEPT_STATUS:
            reasons.append(f"mandatory ordinary-test check {cid!r} is {st} (must be {ACCEPT_STATUS})")
    if not checks:
        reasons.append("EMPTY_CHECK_SET: the receipt records no executed checks; it establishes nothing")

    req_statuses: dict[str, str] = {}
    counterexamples: list[dict] = []
    for req in (approved_contract.get("requirements") or []):
        rid = req.get("id")
        rc = by_id.get(f"req:{rid}")
        if rc is None:
            reasons.append(f"INCOMPLETE_COVERAGE: approved requirement {rid!r} has no qualifying check")
            req_statuses[rid] = "MISSING"
            continue
        st = rc.get("status")
        req_statuses[rid] = st
        if st not in SUPPORTED_STATUSES:
            reasons.append(f"requirement {rid!r} has UNKNOWN_STATUS {st!r}")
        elif st != ACCEPT_STATUS:
            reasons.append(f"requirement {rid!r} is {st}")
            counterexamples.append(_counterexample(rc))

    non_verified = [{"id": c.get("id"), "status": c.get("status"), "label": c.get("label"),
                     "detail": c.get("detail")}
                    for c in checks if isinstance(c, dict) and c.get("status") != ACCEPT_STATUS]
    for c in non_verified:
        if not str(c["id"]).startswith("req:") and c["id"] not in MANDATORY_TEST_CHECKS:
            reasons.append(f"check {c['id']!r} is {c['status']} (all executed checks must be VERIFIED)")
            if c["status"] == "CONTRADICTED":
                counterexamples.append(_counterexample(by_id.get(c["id"]) or {}))

    # ---- 8. Change scope: authorised paths only; test/dependency changes force review -------- #
    allowed = approved_contract.get("allowedPaths")
    changes = receipt.get("changes") or []
    scope: dict[str, Any] = {"allowed_paths": allowed, "changes": [], "out_of_scope": [],
                             "unauthorised_classification": [], "test_changes": [],
                             "dependency_changes": []}
    for ch in changes:
        p = ch.get("path", "")
        cls = ch.get("classification")
        scope["changes"].append({"path": p, "kind": ch.get("kind"), "classification": cls,
                                 "reason": ch.get("reason")})
        if allowed is not None and not any(p == a or p.startswith(a.rstrip("/") + "/") for a in allowed):
            scope["out_of_scope"].append(p)
        if cls != ACCEPT_STATUS:
            scope["unauthorised_classification"].append({"path": p, "classification": cls})
        if is_test_path(p):
            scope["test_changes"].append(p)
        if is_dependency_path(p):
            scope["dependency_changes"].append(p)
    integrity["change_scope"] = scope
    if scope["out_of_scope"]:
        reasons.append(f"OUT_OF_SCOPE_CHANGES: {scope['out_of_scope']} are outside the approved "
                       f"allowedPaths {allowed}; human review required")
    if scope["unauthorised_classification"]:
        reasons.append(f"UNAUTHORISED_CHANGE_CLASSIFICATION: {scope['unauthorised_classification']}")
    if scope["test_changes"]:
        reasons.append(f"TEST_MODIFICATION_REQUIRES_REVIEW: {scope['test_changes']} (possible test weakening)")
    if scope["dependency_changes"]:
        reasons.append(f"DEPENDENCY_CHANGE_REQUIRES_REVIEW: {scope['dependency_changes']}")

    # ---- 9. Exit-status consistency --------------------------------------------------------- #
    integrity["exit_code"] = exit_code
    if exit_code == EXIT_USAGE:
        reasons.append("Sentinel exited 2 (usage/infrastructure error): no trustworthy verification occurred")
    elif exit_code == EXIT_PASSED and status != ACCEPT_STATUS:
        reasons.append(f"INCONSISTENT_VERDICT: exit 0 (scoped checks passed) but receipt status is {status!r}")
    elif exit_code == EXIT_NOT_ACCEPTED and status == ACCEPT_STATUS:
        reasons.append(f"INCONSISTENT_VERDICT: receipt status VERIFIED but Sentinel exited {exit_code}")

    # ---- 10. Verdict ------------------------------------------------------------------------ #
    if status == REVIEW_STATUS:
        reasons.append("UNRESOLVED_REVIEW: Sentinel requires human judgement; not auto-accepted")
    if status == "ENVIRONMENT FAILURE":
        reasons.append("ENVIRONMENT_FAILURE: reliable verification did not complete")
    if status == "UNVERIFIED":
        reasons.append("UNVERIFIED: evidence is insufficient to accept")

    ok = (status == ACCEPT_STATUS) and not reasons
    bindings = {
        "receipt_hash": receipt_hash or receipt.get("id"),
        "contract_hash": receipt.get("contractHash"),
        "candidate_hash": receipt.get("candidateHash"),
        "baseline_hash": receipt.get("baselineHash"),
        "git_head": git.get("head"), "git_branch": git.get("branch"), "git_dirty": git.get("dirty"),
        "runner": runner, "verifier_version": rt.get("verifierVersion"),
        "vitest": rt.get("vitest"), "node": rt.get("node"),
        "worker_sha256": rt.get("workerSha256"), "duration_ms": receipt.get("durationMs"),
    }
    integrity["attempt_id"] = attempt_id
    disclosure = {
        "schema": "shipguard/verification-disclosure/v1",
        "attempt_id": attempt_id,
        "verifier": {"name": "sentinel-verified", "pinned_commit": "becba502c8dbebdd5e52b8ca09122f86e4e37bb3",
                     "version": rt.get("verifierVersion"), "runner": runner},
        "accepted": ok,
        "status": status,
        "receipt": {
            "hash": receipt_hash,
            "sha256_of_receipt_bytes_verified": integrity.get("receipt_content_address_ok"),
            "bytes_published": False,
            "note": ("The receipt hash is the content-address of the receipt bytes. The raw bytes are "
                     "retained in the local verifier store for replay and are NOT published here, "
                     "because they embed absolute local filesystem paths. A published hash without its "
                     "bytes is an identifier, not independently verifiable evidence; see "
                     "independent_checks below for what a third party CAN re-check."),
        },
        "contract": {"sha256_object_key": receipt.get("contractHash"),
                     "deep_equals_approved": receipt.get("contract") == approved_contract,
                     "requirements": [r.get("id") for r in (approved_contract.get("requirements") or [])]},
        "candidate": {"snapshot_object_key": receipt.get("candidateHash"),
                      "file_hashes": {k: v.get("hash") for k, v in
                                      ((candidate_snap or {}).get("files") or {}).items()},
                      "identity_independently_verified":
                          bool(integrity.get("candidate_identity", {}).get("files_hash_matched"))
                          and not integrity.get("candidate_identity", {}).get("files_mismatched")},
        "git": {"head": git.get("head"), "branch": git.get("branch"), "dirty": git.get("dirty")},
        "requirement_results": req_statuses,
        "ordinary_test_results": ordinary,
        "checks_executed": len(checks),
        "non_verified_checks": non_verified,
        "change_scope": scope,
        "counterexamples": counterexamples,
        "integrity": integrity,
        "reasons": reasons,
    }
    return SentinelVerdict(ok=ok, status=(status if status in SUPPORTED_STATUSES else "EVIDENCE_UNKNOWN_STATUS"),
                           reasons=reasons, counterexamples=counterexamples, requirements=req_statuses,
                           ordinary_tests=ordinary, bindings=bindings, integrity=integrity,
                           changes=scope["changes"], non_verified_checks=non_verified,
                           duplicate_check_ids=dupes, receipt_hash=receipt_hash,
                           report_path=report_path, exit_code=exit_code, attempt_id=attempt_id,
                           disclosure=disclosure, raw=receipt)


def run_sentinel_verify(*, repo: Path, contract_path: Path, store: Path, baseline: str = "HEAD",
                        sentinel: list[str] | str | None = None, allow_local: bool = True,
                        runner: str = "local", timeout: int = 300, attempt_id: str | None = None,
                        fresh_store: bool = True, extra_args: list[str] | None = None) -> SentinelVerdict:
    """Run the real ``sentinel verify`` for ONE attempt and validate its evidence.

    ``fresh_store`` (default) gives every attempt a unique store subdirectory, so a receipt can only
    have been produced by this attempt. The store pointer is also required to change, so a failed or
    interrupted invocation can never be answered with an earlier VERIFIED receipt.
    """
    cli = sentinel if isinstance(sentinel, list) else find_sentinel(sentinel)
    repo = Path(repo); contract_path = Path(contract_path)
    attempt_id = attempt_id or uuid.uuid4().hex[:12]
    base_store = Path(store)
    use_store = base_store / f"attempt-{attempt_id}" if fresh_store else base_store

    if cli is None:
        return _fail("ENVIRONMENT_FAILURE",
                     ["sentinel CLI not found (set SHIPGUARD_SENTINEL or install sentinel)"],
                     attempt_id=attempt_id)
    if not contract_path.exists():
        return _fail("ENVIRONMENT_FAILURE", [f"approved contract not found: {contract_path}"],
                     attempt_id=attempt_id)
    try:
        approved_contract = json.loads(contract_path.read_text())
    except Exception as e:  # noqa: BLE001
        return _fail("ENVIRONMENT_FAILURE", [f"approved contract is not valid JSON: {e}"],
                     attempt_id=attempt_id)

    use_store.mkdir(parents=True, exist_ok=True)
    pointer_before = _pointer(use_store)          # None for a fresh store; stale pointer otherwise

    cmd = [*cli, "verify", "--baseline", baseline, "--contract", str(contract_path),
           "--store", str(use_store), "--repo", str(repo), "--runner", runner]
    if allow_local and runner == "local":
        cmd.append("--allow-local")
    cmd += (extra_args or [])

    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           stdin=subprocess.DEVNULL, cwd=str(repo))
    except subprocess.TimeoutExpired:
        return _fail("ENVIRONMENT_FAILURE", [f"sentinel verify timed out after {timeout}s"],
                     attempt_id=attempt_id, integrity={"pointer_before": pointer_before})
    except Exception as e:  # noqa: BLE001
        return _fail("ENVIRONMENT_FAILURE", [f"sentinel verify failed to run: {e}"],
                     attempt_id=attempt_id, integrity={"pointer_before": pointer_before})

    pointer_after = _pointer(use_store)
    lv = use_store / "latest-verification.json"
    if not lv.exists() or not pointer_after:
        tail = ((p.stderr or "") + (p.stdout or ""))[-600:].strip()
        return _fail("ENVIRONMENT_FAILURE",
                     [f"sentinel produced no receipt (exit {p.returncode}): {tail}"],
                     exit_code=p.returncode, attempt_id=attempt_id,
                     integrity={"pointer_before": pointer_before, "pointer_after": None,
                                "fresh_receipt": False})
    if pointer_before and pointer_after == pointer_before:
        # Invocation finished but did not record new evidence: never accept the old receipt.
        return _fail("EVIDENCE_STALE_RECEIPT",
                     [f"STALE_RECEIPT_REUSE: sentinel exited {p.returncode} but the store pointer is "
                      f"unchanged ({pointer_after[:12]}…); refusing to reuse earlier evidence"],
                     receipt_hash=pointer_after, exit_code=p.returncode, attempt_id=attempt_id,
                     integrity={"pointer_before": pointer_before, "pointer_after": pointer_after,
                                "fresh_receipt": False})

    rp = use_store / "objects" / pointer_after
    if not rp.exists():
        return _fail("EVIDENCE_MISSING_RECEIPT",
                     [f"store points at receipt {pointer_after[:12]}… which is not in the store"],
                     receipt_hash=pointer_after, exit_code=p.returncode, attempt_id=attempt_id)
    try:
        receipt = json.loads(rp.read_bytes())
    except Exception as e:  # noqa: BLE001
        return _fail("EVIDENCE_UNPARSEABLE", [f"receipt is not valid JSON: {e}"],
                     receipt_hash=pointer_after, exit_code=p.returncode, attempt_id=attempt_id)

    ptr = {}
    try:
        ptr = json.loads(lv.read_text())
    except Exception:  # noqa: BLE001
        pass
    return evaluate_receipt(receipt, approved_contract, receipt_hash=pointer_after,
                            report_path=str(ptr.get("report") or ""), store=use_store,
                            repo=repo, exit_code=p.returncode, attempt_id=attempt_id,
                            pointer_before=pointer_before)


def latest_store_dir(store: Path) -> Path | None:
    """Return the most recent per-attempt store directory (for local replay of raw receipts)."""
    store = Path(store)
    if not store.exists():
        return None
    cands = sorted([p for p in store.iterdir() if p.is_dir() and p.name.startswith("attempt-")],
                   key=lambda p: p.stat().st_mtime)
    return cands[-1] if cands else (store if (store / "latest-verification.json").exists() else None)

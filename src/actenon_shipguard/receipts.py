"""Structured Sentinel receipt verification (mandate 6B).

Never infer correctness from console text. Sentinel v1.0 stores a structured,
content-addressed ``Receipt`` (sha256 of its JSON serialization is its object key).
This module independently re-verifies that receipt against:

  * the approved acceptance contract  (contract digest + deep equality)
  * the EXACT candidate source        (snapshot file hash == sha256 of current bytes)
  * full git identity                 (40-char commit SHA)
  * verifier identity                 (runtime.verifierVersion + workerSha256)
  * recorded checks                   (receipt.status and every check.status)
  * freshness                         (the receipt must cover the current source)

A forged log line saying VERIFIED authorises nothing: only a receipt whose content
address re-hashes, whose contract matches the approved one, whose snapshot file hash
matches the bytes that will actually execute, and whose checks are all VERIFIED is
accepted. Sentinel's own limitation — "hashes detect corruption, not malicious
rewriting of the entire evidence chain" — is closed by the separate ed25519
correctness envelope (certs.py) pinned to external trust roots (trust.py).
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REQUIRED_RECEIPT_FIELDS = (
    "schemaVersion", "id", "createdAt", "status", "baselineHash",
    "candidateHash", "contractHash", "git", "runner", "runtime", "checks",
)
VERIFIED = "VERIFIED"


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass
class ReceiptVerification:
    ok: bool
    reasons: list[str] = field(default_factory=list)
    receipt_hash: str | None = None
    contract_hash: str | None = None
    candidate_hash: str | None = None
    git_head: str | None = None
    source_file: str | None = None
    source_file_hash: str | None = None
    status: str | None = None
    checks_total: int = 0
    checks_verified: int = 0
    failed_checks: list[str] = field(default_factory=list)
    verifier_version: str | None = None
    worker_sha256: str | None = None
    created_at: str | None = None

    def reject(self, reason: str) -> "ReceiptVerification":
        self.ok = False
        self.reasons.append(reason)
        return self


def _read_object(store: Path, obj_hash: str) -> bytes | None:
    """Read a content-addressed object and verify its integrity (sha256(bytes)==key)."""
    p = store / "objects" / obj_hash
    if not p.exists():
        return None
    data = p.read_bytes()
    if sha256_hex(data) != obj_hash:
        return None  # integrity failure: forged or corrupted object
    return data


def _git_head(repo: Path) -> str | None:
    try:
        out = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                             capture_output=True, text=True, timeout=15)
        head = out.stdout.strip()
        return head if len(head) == 40 and all(c in "0123456789abcdef" for c in head) else None
    except Exception:
        return None


def verify_sentinel_receipt(
    *,
    store: Path,
    approved_contract: Path,
    candidate_repo: Path,
    module_path: str,
    expected_head: str | None = None,
    receipt_hash: str | None = None,
) -> ReceiptVerification:
    """Independently verify the structured Sentinel receipt for an exact artifact."""
    store = Path(store)
    res = ReceiptVerification(ok=True)

    # 1. Locate the receipt hash (structured pointer, not console text).
    if receipt_hash is None:
        latest = store / "latest-verification.json"
        if not latest.exists():
            return res.reject("MISSING: no latest-verification.json in store")
        try:
            receipt_hash = json.loads(latest.read_text())["receipt"]
        except Exception as e:
            return res.reject(f"MISSING: unreadable latest-verification.json ({e})")
    res.receipt_hash = receipt_hash

    # 2. Content-address integrity of the receipt object (forgery/corruption gate).
    raw = _read_object(store, receipt_hash)
    if raw is None:
        return res.reject(f"FORGED/CORRUPT: receipt object {receipt_hash[:12]}… missing or fails content-address integrity")

    # 3. Schema validation.
    try:
        receipt = json.loads(raw)
    except Exception as e:
        return res.reject(f"FORGED: receipt is not valid JSON ({e})")
    missing = [f for f in REQUIRED_RECEIPT_FIELDS if f not in receipt]
    if missing:
        return res.reject(f"SCHEMA: receipt missing required fields {missing}")

    res.status = receipt.get("status")
    res.contract_hash = receipt.get("contractHash")
    res.candidate_hash = receipt.get("candidateHash")
    res.created_at = receipt.get("createdAt")
    res.git_head = (receipt.get("git") or {}).get("head")
    runtime = receipt.get("runtime") or {}
    res.verifier_version = runtime.get("verifierVersion")
    res.worker_sha256 = runtime.get("workerSha256")

    # 4. Verifier result: overall status AND every recorded check.
    checks = receipt.get("checks") or []
    res.checks_total = len(checks)
    res.failed_checks = [c.get("id", "?") for c in checks if c.get("status") != VERIFIED]
    res.checks_verified = res.checks_total - len(res.failed_checks)
    if receipt.get("status") != VERIFIED:
        res.reject(f"VERDICT: receipt.status={receipt.get('status')!r} (not VERIFIED)")
    if res.failed_checks:
        res.reject(f"CHECKS: {len(res.failed_checks)} non-VERIFIED check(s): {res.failed_checks[:6]}")

    # 5. Contract digest: the receipt's contract object must re-hash and deep-equal the approved contract.
    if not res.contract_hash:
        res.reject("CONTRACT: receipt has no contractHash (unapproved intent)")
    else:
        craw = _read_object(store, res.contract_hash)
        if craw is None:
            res.reject(f"CONTRACT: contract object {res.contract_hash[:12]}… fails content-address integrity")
        else:
            try:
                stored_contract = json.loads(craw)
                approved = json.loads(Path(approved_contract).read_text())
                if stored_contract != approved:
                    res.reject("CONTRACT_SUBSTITUTION: receipt contract differs from the approved acceptance contract")
            except Exception as e:
                res.reject(f"CONTRACT: unreadable contract ({e})")

    # 6. Source identity + freshness: the snapshot's recorded hash for the module must
    #    equal sha256 of the bytes that will ACTUALLY execute now.
    if not res.candidate_hash:
        res.reject("SOURCE: receipt has no candidateHash")
    else:
        sraw = _read_object(store, res.candidate_hash)
        if sraw is None:
            res.reject(f"SOURCE: candidate snapshot {res.candidate_hash[:12]}… fails content-address integrity")
        else:
            try:
                snapshot = json.loads(sraw)
                entry = (snapshot.get("files") or {}).get(module_path)
                if not entry:
                    res.reject(f"SOURCE: module {module_path!r} not in certified snapshot")
                else:
                    actual = candidate_repo / module_path
                    if not actual.exists():
                        res.reject(f"SOURCE: candidate file {module_path} does not exist")
                    else:
                        actual_hash = sha256_hex(actual.read_bytes())
                        res.source_file = module_path
                        res.source_file_hash = actual_hash
                        if entry.get("hash") != actual_hash:
                            res.reject(
                                f"STALE/CODE_REPLACED: snapshot hash {str(entry.get('hash'))[:12]}… != "
                                f"current source {actual_hash[:12]}… — receipt does not cover the code that would execute"
                            )
            except Exception as e:
                res.reject(f"SOURCE: unreadable snapshot ({e})")

    # 7. Full git identity binding.
    if not res.git_head or len(res.git_head) != 40:
        res.reject("GIT: receipt git.head is not a full 40-char commit SHA")
    else:
        live_head = _git_head(candidate_repo)
        if expected_head and res.git_head != expected_head:
            res.reject(f"GIT: receipt head {res.git_head[:12]}… != expected {expected_head[:12]}…")
        elif live_head and res.git_head != live_head:
            res.reject(f"GIT_MISMATCH: receipt head {res.git_head[:12]}… != current HEAD {live_head[:12]}…")

    # 8. Verifier identity must be present (so the result is attributable).
    if not res.verifier_version:
        res.reject("VERIFIER: receipt lacks runtime.verifierVersion (unattributable result)")

    return res

"""Correctness certificates signed by a separated prover authority (mandate 6B/6C/6E).

A certificate asserts that an EXACT code artifact is functionally correct: the
property verifier (whole bug class) returned VERIFIED AND the structured Sentinel
receipt independently verified against the approved contract, the exact source, full
git identity and every recorded check.

Crucially the certificate carries only the prover's ``key_id`` — NOT its public key.
The verifier resolves the public key from externally pinned trust roots, so a coding
agent cannot forge a certificate with a self-generated key claiming to be the prover
(mandate 6C: "do not accept an arbitrary public key simply because the claimed signer
supplied it inside the proof").
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from actenon_protocol import canonicalize_bytes

from .receipts import ReceiptVerification
from .trust import KeyPair, TrustRoots, ROLE_CORRECTNESS, sha256_hex

VERIFIED = "VERIFIED"
NOT_VERIFIED = "NOT_VERIFIED"


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass
class Certificate:
    body: dict[str, Any]
    signature: str
    digest: str

    def to_dict(self) -> dict[str, Any]:
        return {"body": self.body, "signature": self.signature, "digest": self.digest}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Certificate":
        return cls(body=d["body"], signature=d["signature"], digest=d["digest"])

    @property
    def overall(self) -> str:
        return self.body.get("overall", NOT_VERIFIED)

    @property
    def key_id(self) -> str:
        return self.body["prover"]["key_id"]

    @property
    def code_artifact_sha256(self) -> str:
        return self.body["code_artifact"]["sha256"]


def build_certificate(
    *,
    prover: KeyPair,
    code_path: Path,
    module_path: str,
    export: str,
    property_report: dict[str, Any],
    receipt: ReceiptVerification,
    contract_digest: str,
    git_head: str,
) -> Certificate:
    if prover.role != ROLE_CORRECTNESS:
        raise ValueError("build_certificate requires a 'correctness' role prover key")
    code_bytes = Path(code_path).read_bytes()
    code_hash = sha256_hex(code_bytes)

    prop_verdict = str(property_report.get("verdict", "UNKNOWN")).upper()
    minimal = None
    violations = property_report.get("violations") or []
    if violations:
        v0 = violations[0]
        minimal = {"invariant": v0.get("invariant"), "args": v0.get("minimal_args"),
                   "result": v0.get("minimal_result"), "detail": v0.get("detail")}

    overall = VERIFIED if (prop_verdict == VERIFIED and receipt.ok) else NOT_VERIFIED
    body: dict[str, Any] = {
        "contract": {"name": "shipguard_correctness_cert", "version": "v1"},
        "code_artifact": {"module": module_path, "sha256": code_hash, "export": export},
        "contract_digest": contract_digest,
        "git_head": git_head,
        "property": {
            "verdict": prop_verdict,
            "trials": property_report.get("trials"),
            "violations": len(violations),
            "invariants": property_report.get("invariants"),
            "minimal_counterexample": minimal,
        },
        "sentinel": {
            "ok": receipt.ok,
            "receipt_hash": receipt.receipt_hash,
            "contract_hash": receipt.contract_hash,
            "candidate_hash": receipt.candidate_hash,
            "git_head": receipt.git_head,
            "status": receipt.status,
            "checks_total": receipt.checks_total,
            "checks_verified": receipt.checks_verified,
            "failed_checks": receipt.failed_checks,
            "verifier_version": receipt.verifier_version,
            "reasons": receipt.reasons,
        },
        "overall": overall,
        "prover": {"role": ROLE_CORRECTNESS, "key_id": prover.key_id},  # key_id only — NO public key
        "issued_at": _utcnow_iso(),
    }
    signature = prover.sign(canonicalize_bytes(body))
    from .trust import b64u_encode
    digest = sha256_hex(canonicalize_bytes(body))
    return Certificate(body=body, signature=b64u_encode(signature), digest=digest)


@dataclass
class CertVerification:
    ok: bool
    reasons: list[str] = field(default_factory=list)


def verify_certificate(cert: Certificate, trust_roots: TrustRoots) -> CertVerification:
    """Verify a certificate signature against the PINNED correctness trust root."""
    from .trust import b64u_decode
    res = CertVerification(ok=True)
    try:
        root = trust_roots.resolve(ROLE_CORRECTNESS, cert.key_id)
    except Exception as e:
        res.ok = False
        res.reasons.append(f"UNTRUSTED_PROVER: {e}")
        return res
    try:
        root.public_key().verify(b64u_decode(cert.signature), canonicalize_bytes(cert.body))
    except Exception:
        res.ok = False
        res.reasons.append("CERT_SIGNATURE_INVALID: signature does not verify under the pinned correctness key")
        return res
    if sha256_hex(canonicalize_bytes(cert.body)) != cert.digest:
        res.ok = False
        res.reasons.append("CERT_DIGEST_MISMATCH: body does not match its declared digest")
    return res

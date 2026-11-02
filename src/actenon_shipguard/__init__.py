"""Actenon ShipGuard — your AI agent says it's done. ShipGuard checks before it ships.

Independent verification + protected consequential execution for AI coding agents.
The trust boundary separates four parties: the authority issuer (signs Actenon proofs
and gate authorizations), the correctness prover (signs correctness certificates), the
enforcer/gate (verifies against externally pinned trust roots; cannot be forged by the
agent), and the requester/agent (holds no signing key).
"""
from __future__ import annotations

__version__ = "0.1.2"

from .trust import (
    KeyPair, TrustRoots, TrustRoot, UntrustedKeyError,
    ROLE_AUTHORITY, ROLE_CORRECTNESS, ROLE_RECONCILIATION, generate_trust_roots,
    public_jwk, jwk_thumbprint, sha256_hex, sign_domain, verify_domain,
    DOMAIN_CORRECTNESS_CERT, DOMAIN_RECONCILIATION, DOMAIN_LEDGER,
)
from .nonce import (
    NonceStore, ReplayRefused, ReconciliationVerifier, sign_reconciliation_statement,
    RESERVED, COMMITTED, ROLLED_BACK,
)
from .receipts import verify_sentinel_receipt, ReceiptVerification
from .certs import Certificate, build_certificate, verify_certificate, VERIFIED, NOT_VERIFIED
from .proofs import AuthoritySigner, AuthorityVerifier, build_intent, mint_proof, verify_proof
from .gate import EdgeGate, ProtectedResource, GateDecision, ALLOW, REFUSE

__all__ = [
    "__version__",
    "KeyPair", "TrustRoots", "TrustRoot", "UntrustedKeyError",
    "ROLE_AUTHORITY", "ROLE_CORRECTNESS", "ROLE_RECONCILIATION", "generate_trust_roots",
    "public_jwk", "jwk_thumbprint", "sha256_hex", "sign_domain", "verify_domain",
    "DOMAIN_CORRECTNESS_CERT", "DOMAIN_RECONCILIATION", "DOMAIN_LEDGER",
    "NonceStore", "ReplayRefused", "ReconciliationVerifier", "sign_reconciliation_statement",
    "RESERVED", "COMMITTED", "ROLLED_BACK",
    "verify_sentinel_receipt", "ReceiptVerification",
    "Certificate", "build_certificate", "verify_certificate", "VERIFIED", "NOT_VERIFIED",
    "AuthoritySigner", "AuthorityVerifier", "build_intent", "mint_proof", "verify_proof",
    "EdgeGate", "ProtectedResource", "GateDecision", "ALLOW", "REFUSE",
]

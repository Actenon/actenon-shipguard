"""Independent trust roots and signing-authority separation.

Mandate 6C: a signature is useful only when the verifier knows which signer it
trusts. ShipGuard never accepts a public key merely because the claimed signer
supplied it inside the proof. Trusted identities are PINNED in an external
``trust-roots.json`` that the coding agent cannot write, and the issuing
authority is separated from the enforcement component:

  * authority issuer  — holds the Actenon proof signing key (mints PCCBs)
  * correctness prover — holds the correctness-certificate signing key
  * enforcer (gate)    — holds ONLY the pinned public trust roots; it verifies, it
                         cannot sign
  * requester (agent)  — holds NO signing key; it can only request

Keys are ed25519. Trust roots support rotation (multiple keys per role, each with
an explicit not-before / not-after window) and are identified by RFC 7638 JWK
thumbprint so a substituted key is rejected even if it claims a trusted key id.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

ROLE_AUTHORITY = "authority"            # Actenon proof issuer (signs PCCBs)
ROLE_CORRECTNESS = "correctness"        # correctness-certificate prover (signs certs)
ROLE_RECONCILIATION = "reconciliation"  # operator authority (signs reconciliation evidence)
ROLE_VERIFIER = "verifier"              # isolated independent-verifier authority (attests receipts)
KNOWN_ROLES = (ROLE_AUTHORITY, ROLE_CORRECTNESS, ROLE_RECONCILIATION, ROLE_VERIFIER)

# Versioned signature domain separation: every signed object embeds its domain tag in the
# canonicalised signed payload, and verifiers require an exact match, so a signature minted
# for one purpose (e.g. a correctness certificate) can never be replayed as another (e.g.
# reconciliation evidence) even under the same key.
DOMAIN_CORRECTNESS_CERT = "shipguard/correctness-cert/v1"
DOMAIN_RECONCILIATION = "shipguard/reconciliation/v1"
DOMAIN_LEDGER = "shipguard/ledger/v1"
DOMAIN_RECEIPT_ATTESTATION = "shipguard/receipt-attestation/v1"


def b64u_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def b64u_decode(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(d: datetime) -> str:
    return d.isoformat().replace("+00:00", "Z")


def public_jwk(pub: Ed25519PublicKey, key_id: str) -> dict[str, Any]:
    raw = pub.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return {"kty": "OKP", "crv": "Ed25519", "kid": key_id, "use": "sig", "alg": "EdDSA", "x": b64u_encode(raw)}


def jwk_thumbprint(jwk: dict[str, Any]) -> str:
    """RFC 7638 JWK thumbprint (sha256 over the canonical required members)."""
    required = {"crv": jwk["crv"], "kty": jwk["kty"], "x": jwk["x"]}
    canon = json.dumps(required, sort_keys=True, separators=(",", ":")).encode()
    return sha256_hex(canon)


@dataclass
class KeyPair:
    """An ed25519 signing keypair held by ONE authority (issuer or prover)."""

    role: str
    key_id: str
    _priv: Ed25519PrivateKey = field(repr=False)

    @classmethod
    def generate(cls, role: str, key_id: str | None = None) -> "KeyPair":
        if role not in KNOWN_ROLES:
            raise ValueError(f"unknown role {role!r}")
        kid = key_id or f"shipguard-{role}-v1"
        return cls(role=role, key_id=kid, _priv=Ed25519PrivateKey.generate())

    @property
    def public_key(self) -> Ed25519PublicKey:
        return self._priv.public_key()

    def jwk(self) -> dict[str, Any]:
        return public_jwk(self.public_key, self.key_id)

    def thumbprint(self) -> str:
        return jwk_thumbprint(self.jwk())

    def sign(self, message: bytes) -> bytes:
        return self._priv.sign(message)

    def private_pem(self) -> bytes:
        return self._priv.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )

    @classmethod
    def from_private_pem(cls, role: str, key_id: str, pem: bytes) -> "KeyPair":
        return cls(role=role, key_id=key_id, _priv=serialization.load_pem_private_key(pem, password=None))


@dataclass(frozen=True)
class TrustRoot:
    role: str
    key_id: str
    thumbprint: str
    public_jwk: dict[str, Any]
    not_before: str | None = None
    not_after: str | None = None

    def public_key(self) -> Ed25519PublicKey:
        return Ed25519PublicKey.from_public_bytes(b64u_decode(self.public_jwk["x"]))

    def is_active(self, now: datetime | None = None) -> bool:
        now = now or _utcnow()
        for bound, cmp in ((self.not_before, lambda a, b: a >= b), (self.not_after, lambda a, b: a <= b)):
            if bound:
                limit = datetime.fromisoformat(bound.replace("Z", "+00:00"))
                if not cmp(now, limit):
                    return False
        return True


class TrustRoots:
    """Externally pinned trusted verifier identities.

    The enforcer loads these from a file the agent cannot write. A certificate or
    proof is trusted only if its signer's (role, key_id) is pinned AND the supplied
    public key's thumbprint matches the pinned thumbprint (so a substituted key
    claiming a trusted kid is rejected).
    """

    def __init__(self, roots: list[TrustRoot], policy_revision: str = "1"):
        self._roots = roots
        self.policy_revision = policy_revision

    @classmethod
    def load(cls, path: Path) -> "TrustRoots":
        data = json.loads(Path(path).read_text())
        roots = [
            TrustRoot(
                role=r["role"], key_id=r["key_id"], thumbprint=r["thumbprint"],
                public_jwk=r["public_jwk"], not_before=r.get("not_before"), not_after=r.get("not_after"),
            )
            for r in data["roots"]
        ]
        return cls(roots, policy_revision=str(data.get("policy_revision", "1")))

    def write(self, path: Path) -> None:
        payload = {
            "policy_revision": self.policy_revision,
            "roots": [
                {"role": r.role, "key_id": r.key_id, "thumbprint": r.thumbprint,
                 "public_jwk": r.public_jwk, "not_before": r.not_before, "not_after": r.not_after}
                for r in self._roots
            ],
        }
        Path(path).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")

    @classmethod
    def from_keypairs(cls, keypairs: list[KeyPair], policy_revision: str = "1") -> "TrustRoots":
        roots = [
            TrustRoot(role=kp.role, key_id=kp.key_id, thumbprint=kp.thumbprint(),
                      public_jwk=kp.jwk())
            for kp in keypairs
        ]
        return cls(roots, policy_revision=policy_revision)

    def resolve(self, role: str, key_id: str, supplied_jwk: dict[str, Any] | None = None) -> TrustRoot:
        """Return the active pinned root for (role, key_id), rejecting key substitution."""
        matches = [r for r in self._roots if r.role == role and r.key_id == key_id and r.is_active()]
        if not matches:
            raise UntrustedKeyError(f"no active pinned {role} trust root for key_id={key_id!r}")
        root = matches[0]
        if supplied_jwk is not None:
            supplied_tp = jwk_thumbprint(supplied_jwk)
            if supplied_tp != root.thumbprint:
                raise UntrustedKeyError(
                    f"supplied {role} key thumbprint {supplied_tp[:12]}… does not match pinned "
                    f"{root.thumbprint[:12]}… for key_id={key_id!r} (possible key substitution)"
                )
        return root

    def pin_file_digest(self, path: Path) -> str:
        return sha256_hex(Path(path).read_bytes())


class UntrustedKeyError(Exception):
    """Raised when a signer identity is not pinned, expired, or substituted."""


def generate_trust_roots(out_dir: Path, policy_revision: str = "1", *,
                         keys_dir: Path | None = None) -> tuple[TrustRoots, dict[str, KeyPair]]:
    """Bootstrap a separated trust boundary: authority, correctness, reconciliation, verifier keys.

    Only the PUBLIC ``trust-roots.json`` is written to ``out_dir`` (which may be the agent's project
    workspace). The PRIVATE keys are written to ``keys_dir`` — pass a location OUTSIDE the agent's
    readable/writable workspace so the coding agent never holds issuer/prover signing material.

    DOCUMENTED LIMITATION (P0-key-storage): on a single unrestricted OS user, an external 0600
    directory is NOT hostile-agent-resistant isolation — a same-user agent with filesystem access
    could still reach it. That is cooperative-local (advisory) mode. The stronger isolated mode
    requires external custody (KMS/HSM or a restricted service account) and must fail closed when
    unavailable; see cli.cmd_init and SECURITY-REMEDIATION-v0.1.2.md.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)  # public trust-roots location (may be the workspace)
    keys_dir = Path(keys_dir) if keys_dir is not None else (out_dir / "keys")
    keys_dir.mkdir(parents=True, exist_ok=True)
    authority = KeyPair.generate(ROLE_AUTHORITY, "shipguard-authority-v1")
    correctness = KeyPair.generate(ROLE_CORRECTNESS, "shipguard-correctness-v1")
    reconciliation = KeyPair.generate(ROLE_RECONCILIATION, "shipguard-reconciliation-v1")
    verifier = KeyPair.generate(ROLE_VERIFIER, "shipguard-verifier-v1")
    for kp in (authority, correctness, reconciliation, verifier):
        p = keys_dir / f"{kp.role}-{kp.key_id}.pem"
        p.write_bytes(kp.private_pem())
        os.chmod(p, 0o600)
    roots = TrustRoots.from_keypairs([authority, correctness, reconciliation, verifier], policy_revision=policy_revision)
    roots.write(out_dir / "trust-roots.json")
    return roots, {"authority": authority, "correctness": correctness,
                   "reconciliation": reconciliation, "verifier": verifier}


def sign_domain(keypair: KeyPair, domain: str, body: dict[str, Any]) -> str:
    """Sign a canonicalised, domain-separated statement.

    The versioned ``domain`` tag is bound INTO the signed payload, so a signature minted for one
    object type can never be replayed as another (cross-domain separation), even under one key.
    """
    from actenon_protocol import canonicalize_bytes
    return b64u_encode(keypair.sign(canonicalize_bytes({"domain": domain, "body": body})))


def verify_domain(public_key: Ed25519PublicKey, domain: str, body: dict[str, Any], signature_b64: str) -> bool:
    """Verify a domain-separated signature; False on any mismatch (incl. wrong domain)."""
    from actenon_protocol import canonicalize_bytes
    try:
        public_key.verify(b64u_decode(signature_b64), canonicalize_bytes({"domain": domain, "body": body}))
        return True
    except Exception:
        return False

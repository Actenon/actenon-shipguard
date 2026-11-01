"""Actenon authority proofs, bound to correctness evidence (release-1.2.1 compatible).

The authority issuer signs an Actenon PCCB with a REAL ed25519 key (never the public
HMAC dev secret). The correctness certificate digest and the exact code-artifact
digest are bound through the action ``constraints`` — which the PCCB ``action_hash``
covers and the signature commits to — because the pinned released minter
(actenon-kernel==1.2.1) has no ``extensions`` parameter. Tampering with the bound
digests therefore invalidates the proof (PROOF_INVALID), as verified empirically.

Signing authority (issuer) is separated from enforcement (the gate verifies with a
public-only verifier resolved from pinned trust roots) and from the requester (agent),
which holds no key at all.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from .trust import KeyPair, TrustRoots, ROLE_AUTHORITY, b64u_decode, b64u_encode


class AuthoritySigner:
    """Actenon ``Signer``-compatible ed25519 signer held ONLY by the issuer."""

    algorithm = "Ed25519"

    def __init__(self, keypair: KeyPair):
        if keypair.role != ROLE_AUTHORITY:
            raise ValueError("AuthoritySigner requires an 'authority' role keypair")
        self._kp = keypair
        self.key_id = keypair.key_id

    @property
    def public_key(self):
        return self._kp.public_key

    def sign_raw(self, payload: bytes) -> bytes:
        """Raw ed25519 signature over arbitrary canonical bytes (e.g. gate authorizations)."""
        return self._kp.sign(payload)

    def sign(self, payload: bytes):
        from actenon.models import SignatureSpec
        return SignatureSpec(algorithm="Ed25519", key_id=self.key_id, encoding="base64url",
                             value=b64u_encode(self._kp.sign(payload)))

    def verify(self, payload: bytes, signature) -> bool:
        if getattr(signature, "algorithm", None) != "Ed25519" or getattr(signature, "key_id", None) != self.key_id:
            return False  # algorithm-confusion / key-substitution guard
        try:
            self._kp.public_key.verify(b64u_decode(signature.value), payload)
            return True
        except Exception:
            return False


class AuthorityVerifier:
    """Public-only Actenon verifier resolved from a PINNED trust root (cannot sign)."""

    algorithm = "Ed25519"

    def __init__(self, trust_roots: TrustRoots, key_id: str):
        root = trust_roots.resolve(ROLE_AUTHORITY, key_id)  # rejects unpinned/expired/substituted
        self._pub = root.public_key()
        self.key_id = key_id

    @property
    def public_key(self):
        return self._pub

    def verify_raw(self, payload: bytes, signature_b64: str) -> bool:
        """Verify a raw ed25519 signature (e.g. a GateAuthorization capability)."""
        try:
            self._pub.verify(b64u_decode(signature_b64), payload)
            return True
        except Exception:
            return False

    def sign(self, payload: bytes):
        raise RuntimeError("public-key-only authority verifier cannot sign")

    def verify(self, payload: bytes, signature) -> bool:
        if getattr(signature, "algorithm", None) != "Ed25519" or getattr(signature, "key_id", None) != self.key_id:
            return False
        try:
            self._pub.verify(b64u_decode(signature.value), payload)
            return True
        except Exception:
            return False


def _iso(d: datetime) -> str:
    return d.isoformat().replace("+00:00", "Z")


def build_intent(
    *,
    capability: str,
    parameters: dict[str, Any],
    correctness_cert_digest: str,
    code_artifact_sha256: str,
    contract_digest: str,
    git_head: str,
    resource_id: str,
    intent_id: str,
    now: datetime | None = None,
    ttl_minutes: int = 5,
) -> tuple[dict[str, Any], datetime]:
    """Action intent whose constraints bind the correctness cert + exact code + contract + git head.

    Everything security-relevant is inside ``constraints`` so the signed action_hash
    commits to it (mandate 6E: exact execution identity).
    """
    now = now or datetime.now(timezone.utc)
    constraints = {
        "correctness_cert": correctness_cert_digest,
        "code_artifact": f"sha256:{code_artifact_sha256}",
        "contract": f"sha256:{contract_digest}",
        "git_head": git_head,
        **{f"exact_{k}": v for k, v in parameters.items()},
    }
    intent = {
        "contract": {"name": "action_intent", "version": "v1"},
        "intent_id": intent_id,
        "issued_at": _iso(now),
        "expires_at": _iso(now + timedelta(minutes=ttl_minutes)),
        "tenant": {"tenant_id": "tenant_shipguard"},
        "requester": {"type": "service", "id": "shipguard-agent", "display_name": "ShipGuard Agent"},
        "action": {
            "name": capability, "capability": capability,
            "parameters": parameters, "constraints": constraints,
            "scope": {"target_resource_type": "protected_resource", "single_use": True},
        },
        "target": {"resource_type": "protected_resource", "resource_id": resource_id},
        "metadata": {"distribution": "actenon-shipguard"},
        "context": {"product": "shipguard"},
    }
    return intent, now


def mint_proof(
    *,
    signer: AuthoritySigner,
    intent_payload: dict[str, Any],
    now: datetime,
    pccb_id: str,
    nonce: str,
    issuer_id: str = "shipguard-authority-issuer",
):
    """Mint a PCCB on the pinned released actenon-kernel (constraints-bound correctness)."""
    from actenon.api.intake import ActionIntentIntakeService
    from actenon.models import AudienceRef, DynamicContextInput, PartyRef, PolicyDecision
    from actenon.proof import PCCBMinter

    intent = ActionIntentIntakeService().parse(intent_payload)
    action = intent_payload["action"]
    context = DynamicContextInput(
        request_id=f"req-{nonce}",
        audience=AudienceRef(type="service", id="shipguard-protected-endpoint"),
        scope_capabilities=(action["capability"],),
        now=now,
        parameter_constraints=action["constraints"],
        resource_selectors=({"resource_id": intent_payload["target"]["resource_id"]},),
    )
    decision = PolicyDecision(outcome="allow", summary="ShipGuard authority allow for verified action",
                              rule_evaluations=(), reason_codes=("SHIPGUARD_ALLOW",))
    minter = PCCBMinter(signer=signer, issuer=PartyRef(type="service", id=issuer_id, display_name="ShipGuard Authority Issuer"),
                        pccb_id_factory=lambda: pccb_id, nonce_factory=lambda: nonce)
    return minter.mint(intent, decision, context)


def verify_proof(*, trust_roots: TrustRoots, intent_payload: dict[str, Any], pccb_payload: dict[str, Any],
                 now: datetime, request_id: str, key_id: str | None = None):
    """Verify a PCCB at the edge using a public-only verifier resolved from PINNED trust roots.

    The authority identity is taken from the AUTHENTICATED proof data (``pccb.signature.key_id``),
    not from caller assertion, and must resolve to a pinned authority root (else UntrustedKeyError).
    """
    from actenon.models import AudienceRef, DynamicContextInput
    from actenon.verifier import VerifierSDK

    kid = key_id or (pccb_payload.get("signature") or {}).get("key_id")
    if not kid:
        raise ValueError("proof carries no signer key_id; cannot resolve authority identity")
    verifier = AuthorityVerifier(trust_roots, kid)  # raises UntrustedKeyError if not pinned/substituted
    action = intent_payload["action"]
    context = DynamicContextInput(
        request_id=request_id,
        audience=AudienceRef(type="service", id="shipguard-protected-endpoint"),
        scope_capabilities=(action["capability"],),
        now=now,
        parameter_constraints=action["constraints"],
        resource_selectors=({"resource_id": intent_payload["target"]["resource_id"]},),
    )
    return VerifierSDK(verifier).verify(intent=intent_payload, pccb=pccb_payload, context=context)

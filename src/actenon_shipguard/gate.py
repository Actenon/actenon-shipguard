"""The execution-edge enforcement boundary (v0.1.2 P0 signing-authority separation).

OPTION A — smallest attack surface. The protected boundary independently verifies the ORIGINAL
signed authority (Actenon PCCB) and correctness evidence before executing. The enforcer holds ONLY
pinned PUBLIC trust roots: it possesses NO private signing key and therefore cannot mint proofs,
certificates, dispatch capabilities, ledger signatures or reconciliation evidence. There is no
forgeable handoff capability to leak — ``verify_and_execute`` is the ONLY route to the side effect
and it re-verifies the primary evidence every call, so invoking it directly cannot bypass anything.

Separate signing authorities (NONE held here):
  * authority issuer        — signs Actenon PCCBs
  * correctness prover       — signs correctness certificates (domain shipguard/correctness-cert/v1)
  * reconciliation authority — signs reconciliation evidence (domain shipguard/reconciliation/v1),
                               verified by NonceStore's internal trusted verifier, never created here
The authority identity is resolved from the AUTHENTICATED proof data (``pccb.signature.key_id``) and
pinned against the trust roots — not taken on caller assertion.

The decision ledger is tamper-EVIDENT via a hash chain. Unforgeable audit signing would require a
separate audit authority; that is documented as a limitation, not claimed here.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from actenon_protocol import canonicalize_bytes

from .certs import Certificate, verify_certificate
from .nonce import NonceStore, ReplayRefused
from .proofs import verify_proof
from .trust import TrustRoots, sha256_hex

ALLOW = "ALLOW"
REFUSE = "REFUSE"


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass
class GateDecision:
    decision: str
    layer: str
    code: str
    reason: str
    evidence: dict[str, Any] = field(default_factory=dict)

    @property
    def allowed(self) -> bool:
        return self.decision == ALLOW

    def __str__(self) -> str:
        return f"{self.decision} [{self.layer}/{self.code}] {self.reason}"


class ProtectedResource:
    """The consequential action AND its enforcement boundary. Holds NO private key.

    ``verify_and_execute`` is the only route to the side effect; it always verifies proof +
    certificate + exact-code binding + nonce before executing an immutable snapshot of the
    certified bytes. There is deliberately no execute-without-verify method.
    """

    def __init__(self, *, trust_roots: TrustRoots, tsx: Path, out_dir: Path,
                 nonce_store: NonceStore, ledger: Path):
        self._roots = trust_roots          # PUBLIC trust roots only — no signing material
        self._tsx = Path(tsx)
        self._out_dir = Path(out_dir)
        self._nonces = nonce_store
        self._ledger = Path(ledger)
        self._ledger.parent.mkdir(parents=True, exist_ok=True)

    def holds_signing_key(self) -> bool:
        """Self-audit: the enforcer must never possess private signing material."""
        return any(hasattr(self, a) for a in ("_issuer", "_signer", "_priv", "_keypair", "_kp"))

    # ---- immutable-snapshot invocation of the exact certified bytes ----
    def _invoke_certified(self, code_bytes: bytes, export: str, args: list[Any]) -> Any:
        snap_dir = Path(tempfile.mkdtemp(prefix="shipguard-snapshot-"))
        runner = tempfile.NamedTemporaryFile("w", suffix=".mjs", delete=False)
        runner.write(
            "import { pathToFileURL } from 'node:url';\n"
            "const m = await import(pathToFileURL(process.argv[2]).href);\n"
            "const fn = process.argv[3];\n"
            "const args = JSON.parse(process.argv[4]);\n"
            "console.log(JSON.stringify(m[fn](...args)));\n"
        )
        runner.close()
        snapshot = snap_dir / "certified.ts"
        try:
            snapshot.write_bytes(code_bytes)   # exact bytes that were hashed
            snapshot.chmod(0o444)              # immutable snapshot (same-user caveat documented)
            if sha256_hex(snapshot.read_bytes()) != sha256_hex(code_bytes):
                raise RuntimeError("snapshot digest does not match the certified bytes")
            proc = subprocess.run(
                [str(self._tsx), runner.name, str(snapshot), export, json.dumps(args)],
                capture_output=True, text=True, timeout=30)
            if proc.returncode != 0:
                raise RuntimeError(f"certified invocation failed: {proc.stderr.strip()[:300]}")
            return json.loads(proc.stdout.strip().splitlines()[-1])
        finally:
            Path(runner.name).unlink(missing_ok=True)
            shutil.rmtree(snap_dir, ignore_errors=True)

    def verify_and_execute(self, *, intent_payload: dict[str, Any], pccb_payload: dict[str, Any],
                           cert: Certificate, code_path: Path, module_path: str, export: str,
                           parameters: dict[str, Any], resource_id: str,
                           now: datetime | None = None) -> GateDecision:
        now = now or datetime.now(timezone.utc)
        constraints = intent_payload["action"]["constraints"]

        # 1. AUTHORITY — verify the PCCB; authority identity resolved from the proof + pinned roots.
        try:
            verified = verify_proof(trust_roots=self._roots, intent_payload=intent_payload,
                                    pccb_payload=pccb_payload, now=now,
                                    request_id=f"req-{pccb_payload.get('nonce', 'x')}")
        except Exception as e:
            return self._decide(REFUSE, "AUTHORITY", "PROOF_INVALID",
                                f"authority proof failed: {getattr(e, 'refusal_code', e)}")

        # 2. INTENT EQUALITY — every executed value must equal the verified authorised intent.
        vaction = verified.pccb.action
        auth_params = dict(vaction.parameters)
        auth_resource = verified.pccb.target.resource_id
        mism = []
        if parameters != auth_params:
            mism.append(f"parameters {parameters} != authorised {auth_params}")
        if resource_id != auth_resource:
            mism.append(f"resource_id {resource_id!r} != authorised {auth_resource!r}")
        if export != cert.body["code_artifact"]["export"]:
            mism.append(f"export {export!r} != certified {cert.body['code_artifact']['export']!r}")
        if module_path != cert.body["code_artifact"]["module"]:
            mism.append(f"module {module_path!r} != certified {cert.body['code_artifact']['module']!r}")
        if constraints.get("contract", "").replace("sha256:", "") != cert.body.get("contract_digest"):
            mism.append("proof-bound contract digest != certificate contract digest")
        if constraints.get("git_head") != cert.body.get("git_head"):
            mism.append("proof-bound git commit != certificate git commit")
        if mism:
            return self._decide(REFUSE, "AUTHORITY", "INTENT_MISMATCH",
                                "executed action does not equal the verified authorised intent: " + "; ".join(mism),
                                {"authorised_capability": vaction.capability})

        # 3. CORRECTNESS — certificate under the pinned correctness root (domain-separated).
        cv = verify_certificate(cert, self._roots)
        if not cv.ok:
            return self._decide(REFUSE, "CORRECTNESS", "CERT_UNTRUSTED", "; ".join(cv.reasons))
        if cert.overall != "VERIFIED":
            p, s = cert.body["property"], cert.body["sentinel"]
            return self._decide(REFUSE, "CORRECTNESS", "NOT_VERIFIED",
                                f"correctness {cert.overall} (property={p['verdict']}, sentinel_ok={s['ok']}, "
                                f"failed_checks={s['failed_checks'][:4]})")

        # 4. EXACT-CODE BINDING — proof constraint == certificate == sha256(actual bytes).
        code_bytes = Path(code_path).read_bytes()
        actual_hash = sha256_hex(code_bytes)
        bound_code = constraints.get("code_artifact", "").replace("sha256:", "")
        if not (bound_code == cert.code_artifact_sha256 == actual_hash):
            return self._decide(REFUSE, "CORRECTNESS", "CODE_ARTIFACT_MISMATCH",
                                f"proof-bound {bound_code[:12]}… / cert {cert.code_artifact_sha256[:12]}… / "
                                f"actual {actual_hash[:12]}… disagree")
        if constraints.get("correctness_cert", "").replace("sha256:", "") != cert.digest:
            return self._decide(REFUSE, "CORRECTNESS", "CERT_DIGEST_MISMATCH",
                                "proof does not commit to this certificate")

        nonce = pccb_payload.get("nonce")
        effect_id = sha256_hex(canonicalize_bytes(
            {"resource": auth_resource, "params": auth_params, "nonce": nonce}))

        # 5. NONCE — durable reservation BEFORE any side effect.
        try:
            self._nonces.reserve(nonce=nonce, pccb_id=pccb_payload.get("pccb_id", ""), effect_id=effect_id)
        except ReplayRefused as e:
            return self._decide(REFUSE, "REPLAY", e.code, e.message, {"nonce_state": e.state})

        # 6. EXECUTE the immutable snapshot of the exact certified bytes (the real side effect).
        try:
            shares = self._invoke_certified(code_bytes, export,
                                            [auth_params["total_pence"], auth_params["parties"]])
        except Exception as e:
            return self._decide(REFUSE, "EXECUTION", "EFFECT_UNCERTAIN",
                                f"side effect did not confirm ({e}); nonce left RESERVED — reconcile with "
                                f"signed evidence, do not blind-retry",
                                {"nonce": nonce, "effect_id": effect_id})
        self._out_dir.mkdir(parents=True, exist_ok=True)
        record = {"allocation_id": auth_params.get("allocation_id", "alloc"),
                  "total_pence": auth_params["total_pence"], "parties": auth_params["parties"],
                  "shares": shares, "conserved": sum(shares) == auth_params["total_pence"],
                  "executed_at": _utcnow_iso(), "nonce": nonce, "resource_id": auth_resource,
                  "code_artifact_sha256": actual_hash}
        tmp = self._out_dir / "disbursement.partial"
        tmp.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        tmp.replace(self._out_dir / "disbursement.json")

        # 7. Confirmed outcome -> commit the nonce durably.
        self._nonces.commit(nonce=nonce, outcome={"disbursement": record, "effect_id": effect_id})
        return self._decide(ALLOW, "OK", "AUTHORISED_AND_CORRECT",
                            "authority proof + correctness cert + intent equality + exact-code binding verified; "
                            "certified snapshot invoked; nonce committed",
                            {"nonce": nonce, "code_artifact_sha256": actual_hash, "cert_digest": cert.digest,
                             "shares": shares, "conserved": record["conserved"]})

    # ---- tamper-evident hash-chained ledger (enforcer cannot sign; it has no key) ----
    def _decide(self, decision, layer, code, reason, evidence=None) -> GateDecision:
        d = GateDecision(decision, layer, code, reason, evidence or {})
        self._append_ledger(d)
        return d

    def _append_ledger(self, d: GateDecision) -> None:
        prev = "genesis"
        if self._ledger.exists():
            lines = [ln for ln in self._ledger.read_text().splitlines() if ln.strip()]
            if lines:
                prev = sha256_hex(lines[-1].encode())
        entry = {"ts": _utcnow_iso(), "prev": prev, "decision": d.decision, "layer": d.layer,
                 "code": d.code, "reason": d.reason, "evidence": d.evidence}
        with self._ledger.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, sort_keys=True) + "\n")


class EdgeGate:
    """Thin facade over the protected boundary. Holds NO signing key; delegates verification+execution."""

    def __init__(self, *, resource: ProtectedResource):
        self._resource = resource

    def authorize_and_execute(self, **kwargs) -> GateDecision:
        return self._resource.verify_and_execute(**kwargs)

"""The execution-edge gate and the protected resource it mediates (mandate 6A/6D/6E).

Trust boundary: the protected resource NEVER executes on its own. It requires a
``GateAuthorization`` capability signed by the authority issuer (a key the coding
agent does not hold) and re-verifies the exact code-artifact digest before invoking
the certified implementation. The disbursement is produced BY calling the certified
``allocate()`` from the exact certified source — there is no synthetic record and no
alternate dispatch path inside the protected boundary.

Gate order (all must hold before any side effect):
  1. Actenon authority proof verifies under a PINNED trust root
  2. correctness certificate verifies under a PINNED trust root and is VERIFIED
  3. proof-bound code/contract digests == certificate digests == sha256(actual bytes)
  4. durable nonce RESERVED (replay + uncertain-outcome protection) before the effect
  5. mediated invocation of the certified artifact
  6. nonce COMMITTED only on a confirmed outcome; a crash leaves it RESERVED so a
     blind retry is refused and the unresolved state is exposed
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

from .certs import Certificate, verify_certificate
from .nonce import NonceStore, ReplayRefused
from .proofs import AuthoritySigner, AuthorityVerifier, verify_proof
from .trust import TrustRoots, ROLE_AUTHORITY, b64u_decode, b64u_encode, sha256_hex
from actenon_protocol import canonicalize_bytes

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


@dataclass
class GateAuthorization:
    """Signed capability the resource requires before it will execute. The agent
    cannot forge it: it is signed by the authority issuer key."""
    nonce: str
    code_artifact_sha256: str
    module_path: str
    export: str
    parameters: dict[str, Any]
    resource_id: str
    expires_at: str
    signature: str

    def to_dict(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in ("nonce", "code_artifact_sha256", "module_path", "export", "parameters", "resource_id", "expires_at", "signature")}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "GateAuthorization":
        return cls(**d)

    def _signable(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in ("nonce", "code_artifact_sha256", "module_path", "export", "parameters", "resource_id", "expires_at")}


class ProtectedResource:
    """The consequential action. Executes ONLY with a valid signed GateAuthorization,
    re-verifies the code digest, and invokes the certified implementation for real."""

    def __init__(self, *, trust_roots: TrustRoots, authority_key_id: str, tsx: Path, out_dir: Path):
        self._verifier = AuthorityVerifier(trust_roots, authority_key_id)  # public-only: cannot sign
        self._tsx = Path(tsx)
        self._out_dir = Path(out_dir)

    def _invoke_certified(self, code_path: Path, export: str, args: list[Any]) -> Any:
        """Mediated invocation: import the EXACT certified artifact and call the export."""
        runner = tempfile.NamedTemporaryFile("w", suffix=".mjs", delete=False)
        runner.write(
            "import { pathToFileURL } from 'node:url';\n"
            "const m = await import(pathToFileURL(process.argv[2]).href);\n"
            "const fn = process.argv[3];\n"
            "const args = JSON.parse(process.argv[4]);\n"
            "console.log(JSON.stringify(m[fn](...args)));\n"
        )
        runner.close()
        try:
            proc = subprocess.run(
                [str(self._tsx), runner.name, str(code_path), export, json.dumps(args)],
                capture_output=True, text=True, timeout=30,
            )
        finally:
            Path(runner.name).unlink(missing_ok=True)
        if proc.returncode != 0:
            raise RuntimeError(f"certified invocation failed: {proc.stderr.strip()[:300]}")
        return json.loads(proc.stdout.strip().splitlines()[-1])

    def execute(self, auth: GateAuthorization, code_path: Path) -> dict[str, Any]:
        # 1. Capability check: a valid issuer signature over the authorization.
        if not auth.signature or not self._verifier.verify_raw(canonicalize_bytes(auth._signable()), auth.signature):
            raise PermissionError("unauthorised: gate authorization signature invalid or missing")
        # 2. Expiry.
        if datetime.fromisoformat(auth.expires_at.replace("Z", "+00:00")) < datetime.now(timezone.utc):
            raise PermissionError("unauthorised: gate authorization expired")
        # 3. TOCTOU elimination: read the certified bytes ONCE, then execute from an immutable
        #    snapshot written from those exact in-memory bytes. The artifact that runs is provably
        #    the artifact that was hashed — the mutable original is never re-read before import.
        #    (Same-OS-account immutability is a documented limit; this closes the check/use race.)
        code_bytes = Path(code_path).read_bytes()
        actual = sha256_hex(code_bytes)
        if actual != auth.code_artifact_sha256:
            raise PermissionError(f"unauthorised: code artifact {actual[:12]}… != authorised {auth.code_artifact_sha256[:12]}…")
        snap_dir = Path(tempfile.mkdtemp(prefix="shipguard-snapshot-"))
        snapshot = snap_dir / "certified.ts"
        try:
            snapshot.write_bytes(code_bytes)
            snapshot.chmod(0o444)
            if sha256_hex(snapshot.read_bytes()) != auth.code_artifact_sha256:
                raise PermissionError("unauthorised: immutable snapshot digest does not match the authorised artifact")
            # 4. Mediated invocation of the certified snapshot — the real side effect.
            total = auth.parameters["total_pence"]
            parties = auth.parameters["parties"]
            shares = self._invoke_certified(snapshot, auth.export, [total, parties])
        finally:
            shutil.rmtree(snap_dir, ignore_errors=True)
        # 5. Atomic write of the disbursement record produced BY the certified code.
        self._out_dir.mkdir(parents=True, exist_ok=True)
        record = {
            "allocation_id": auth.parameters.get("allocation_id", "alloc"),
            "total_pence": total, "parties": parties, "shares": shares,
            "conserved": sum(shares) == total,
            "executed_at": _utcnow_iso(),
            "nonce": auth.nonce, "resource_id": auth.resource_id,
            "code_artifact_sha256": actual,
        }
        tmp = self._out_dir / "disbursement.partial"
        tmp.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        tmp.replace(self._out_dir / "disbursement.json")  # atomic
        return record


class EdgeGate:
    def __init__(self, *, trust_roots: TrustRoots, issuer_signer: AuthoritySigner,
                 nonce_store: NonceStore, resource: ProtectedResource, ledger: Path):
        self._roots = trust_roots
        self._issuer = issuer_signer
        self._nonces = nonce_store
        self._resource = resource
        self._ledger = Path(ledger)
        self._ledger.parent.mkdir(parents=True, exist_ok=True)

    def _sign_auth(self, auth: GateAuthorization) -> GateAuthorization:
        auth.signature = b64u_encode(self._issuer.sign_raw(canonicalize_bytes(auth._signable())))
        return auth

    def _record(self, decision: GateDecision) -> None:
        line = {"ts": _utcnow_iso(), "decision": decision.decision, "layer": decision.layer,
                "code": decision.code, "reason": decision.reason, "evidence": decision.evidence}
        sig = b64u_encode(self._issuer.sign_raw(canonicalize_bytes(line)))
        with self._ledger.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"record": line, "authority_signature": sig}, sort_keys=True) + "\n")

    def authorize_and_execute(
        self, *, intent_payload: dict[str, Any], pccb_payload: dict[str, Any],
        cert: Certificate, code_path: Path, module_path: str, export: str,
        parameters: dict[str, Any], resource_id: str, now: datetime | None = None,
    ) -> GateDecision:
        now = now or datetime.now(timezone.utc)
        constraints = intent_payload["action"]["constraints"]

        # 1. AUTHORITY — Actenon proof under pinned trust root.
        try:
            verified = verify_proof(trust_roots=self._roots, key_id=self._issuer.key_id,
                                    intent_payload=intent_payload, pccb_payload=pccb_payload,
                                    now=now, request_id=f"req-{pccb_payload.get('nonce','x')}")
        except Exception as e:
            d = GateDecision(REFUSE, "AUTHORITY", "PROOF_INVALID", f"authority proof failed: {getattr(e,'refusal_code',e)}")
            self._record(d); return d

        # 1b. INTENT EQUALITY — every value about to execute must EXACTLY equal the verified
        #     authorised intent (parameters, resource identity, capability, certified export/module).
        #     This blocks reusing a valid small-value authorisation for a different, larger action,
        #     and is checked BEFORE any nonce reservation or side effect.
        vaction = verified.pccb.action
        auth_params = dict(vaction.parameters)
        auth_resource = verified.pccb.target.resource_id
        auth_capability = vaction.capability
        mismatches = []
        if parameters != auth_params:
            mismatches.append(f"parameters {parameters} != authorised {auth_params}")
        if resource_id != auth_resource:
            mismatches.append(f"resource_id {resource_id!r} != authorised {auth_resource!r}")
        if export != cert.body["code_artifact"]["export"]:
            mismatches.append(f"export {export!r} != certified {cert.body['code_artifact']['export']!r}")
        if module_path != cert.body["code_artifact"]["module"]:
            mismatches.append(f"module {module_path!r} != certified {cert.body['code_artifact']['module']!r}")
        if mismatches:
            d = GateDecision(REFUSE, "AUTHORITY", "INTENT_MISMATCH",
                             "executed action does not equal the verified authorised intent: " + "; ".join(mismatches),
                             {"authorised_capability": auth_capability})
            self._record(d); return d

        # 2. CORRECTNESS — certificate under pinned trust root.
        cv = verify_certificate(cert, self._roots)
        if not cv.ok:
            d = GateDecision(REFUSE, "CORRECTNESS", "CERT_UNTRUSTED", "; ".join(cv.reasons))
            self._record(d); return d
        if cert.overall != "VERIFIED":
            p, s = cert.body["property"], cert.body["sentinel"]
            d = GateDecision(REFUSE, "CORRECTNESS", "NOT_VERIFIED",
                             f"correctness {cert.overall} (property={p['verdict']}, sentinel_ok={s['ok']}, failed_checks={s['failed_checks'][:4]})")
            self._record(d); return d

        # 3. Exact-execution-identity binding: proof constraints == cert == actual bytes.
        actual_hash = sha256_hex(Path(code_path).read_bytes())
        bound_code = constraints.get("code_artifact", "").replace("sha256:", "")
        if not (bound_code == cert.code_artifact_sha256 == actual_hash):
            d = GateDecision(REFUSE, "CORRECTNESS", "CODE_ARTIFACT_MISMATCH",
                             f"proof-bound {bound_code[:12]}… / cert {cert.code_artifact_sha256[:12]}… / actual {actual_hash[:12]}… disagree")
            self._record(d); return d
        if constraints.get("correctness_cert", "").replace("sha256:", "") != cert.digest:
            d = GateDecision(REFUSE, "CORRECTNESS", "CERT_DIGEST_MISMATCH", "proof does not commit to this certificate")
            self._record(d); return d

        nonce = pccb_payload.get("nonce")
        # Effect identity and the executed values are derived from the VERIFIED intent, never from
        # caller-supplied arguments (which were already required to equal it above).
        effect_id = sha256_hex(canonicalize_bytes({"resource": auth_resource, "params": auth_params, "nonce": nonce}))

        # 4. Durable nonce reservation BEFORE the side effect.
        try:
            self._nonces.reserve(nonce=nonce, pccb_id=pccb_payload.get("pccb_id", ""), effect_id=effect_id)
        except ReplayRefused as e:
            d = GateDecision(REFUSE, "REPLAY", e.code, e.message, {"nonce_state": e.state})
            self._record(d); return d

        # 5. Mediated invocation of the certified artifact (the real consequential action).
        auth = self._sign_auth(GateAuthorization(
            nonce=nonce, code_artifact_sha256=actual_hash, module_path=module_path, export=export,
            parameters=auth_params, resource_id=auth_resource,
            expires_at=_plus_seconds(30), signature="",
        ))
        try:
            record = self._resource.execute(auth, code_path)
        except Exception as e:
            # Uncertain outcome: nonce stays RESERVED; blind retry will be refused.
            d = GateDecision(REFUSE, "EXECUTION", "EFFECT_UNCERTAIN",
                             f"side effect did not confirm ({e}); nonce left RESERVED — reconcile with evidence, do not blind-retry",
                             {"nonce": nonce, "effect_id": effect_id})
            self._record(d); return d

        # 6. Confirmed outcome -> commit the nonce durably.
        self._nonces.commit(nonce=nonce, outcome={"disbursement": record, "effect_id": effect_id})
        d = GateDecision(ALLOW, "OK", "AUTHORISED_AND_CORRECT",
                         "authority proof + correctness cert + exact-code binding verified; certified code invoked; nonce committed",
                         {"nonce": nonce, "code_artifact_sha256": actual_hash, "cert_digest": cert.digest,
                          "shares": record.get("shares"), "conserved": record.get("conserved")})
        self._record(d); return d


def _plus_seconds(n: int) -> str:
    from datetime import timedelta
    return (datetime.now(timezone.utc) + timedelta(seconds=n)).isoformat().replace("+00:00", "Z")

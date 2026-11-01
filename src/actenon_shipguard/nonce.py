"""Durable, atomic, concurrency-safe replay tracking (mandate 6D).

Replaces the earlier in-memory ``set`` of consumed nonces. A locally recorded
ALLOW is NEVER equated with guaranteed exactly-once execution: the nonce is
RESERVED durably *before* the side effect, so a crash mid-effect leaves the nonce
in an uncertain ``reserved`` state and a blind retry is refused until the outcome
is reconciled with signed evidence.

States:  reserved -> committed (effect confirmed) | rolled_back (confirmed not run)
A ``reserved`` nonce with no resolution is an UNCERTAIN outcome.

Backed by SQLite in WAL mode with a UNIQUE constraint on the nonce, claimed
inside a ``BEGIN IMMEDIATE`` transaction so that of two concurrent processes
exactly one wins the claim and the other is refused.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

RESERVED = "reserved"
COMMITTED = "committed"
ROLLED_BACK = "rolled_back"


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class ReplayRefused(Exception):
    def __init__(self, code: str, message: str, state: str | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.state = state


@dataclass
class NonceRecord:
    nonce: str
    pccb_id: str
    effect_id: str
    state: str
    reserved_at: str
    resolved_at: str | None
    outcome: dict[str, Any] | None

    @property
    def uncertain(self) -> bool:
        return self.state == RESERVED


def sign_reconciliation_statement(keypair, *, nonce: str, pccb_id: str, effect_id: str,
                                  resource_id: str, resolution: str, outcome: dict,
                                  policy_revision: str = "1") -> dict:
    """Operator-side: a canonical, versioned, DOMAIN-SEPARATED reconciliation statement.

    Produced by the SEPARATE reconciliation authority (its own ed25519 identity) — never by the
    enforcer or the coding agent. Binds the exact nonce, pccb, effect, resource, resolution,
    outcome, policy revision and issuance time.
    """
    from .trust import DOMAIN_RECONCILIATION, sign_domain
    body = {
        "schema": "shipguard/reconciliation/v1",
        "nonce": nonce, "pccb_id": pccb_id, "effect_id": effect_id, "resource_id": resource_id,
        "resolution": resolution, "outcome": outcome, "policy_revision": str(policy_revision),
        "issued_at": _utcnow(), "reconciler": keypair.key_id,
    }
    return {"body": body, "key_id": keypair.key_id,
            "signature": sign_domain(keypair, DOMAIN_RECONCILIATION, body)}


class ReconciliationVerifier:
    """Trusted, internally-configured reconciliation verifier (NOT a caller-supplied callback).

    Configured with PINNED reconciliation trust roots, so a caller cannot inject ``lambda: True``.
    Verifies the domain-separated signature against the pinned reconciliation authority and binds
    the statement to the exact nonce/pccb/effect/resource/resolution/policy plus a freshness window.
    Any mismatch -> False, leaving the nonce uncertain (fail closed).
    """

    def __init__(self, trust_roots, *, policy_revision: str = "1", max_age_s: int = 300):
        self._roots = trust_roots
        self._policy_revision = str(policy_revision)
        self._max_age_s = max_age_s

    def verify(self, evidence: dict, *, nonce: str, pccb_id: str, effect_id: str,
               resource_id: str, resolution: str) -> bool:
        from .trust import DOMAIN_RECONCILIATION, ROLE_RECONCILIATION, verify_domain
        try:
            body = evidence["body"]; key_id = evidence["key_id"]; sig = evidence["signature"]
        except (KeyError, TypeError):
            return False
        if body.get("schema") != "shipguard/reconciliation/v1":
            return False
        try:
            root = self._roots.resolve(ROLE_RECONCILIATION, key_id)  # rejects unknown/unpinned signer
        except Exception:
            return False
        if not verify_domain(root.public_key(), DOMAIN_RECONCILIATION, body, sig):
            return False  # forged signature or cross-domain replay
        if (body.get("nonce") != nonce or body.get("pccb_id") != pccb_id
                or body.get("effect_id") != effect_id or body.get("resource_id") != resource_id
                or body.get("resolution") != resolution):
            return False  # evidence for a different effect / wrong resolution
        if body.get("policy_revision") != self._policy_revision:
            return False
        try:
            issued = datetime.fromisoformat(body["issued_at"].replace("Z", "+00:00"))
        except Exception:
            return False
        age = (datetime.now(timezone.utc) - issued).total_seconds()
        return not (age < -5 or age > self._max_age_s)  # reject future-dated or stale evidence


class NonceStore:
    def __init__(self, path: Path, recon_verifier: "ReconciliationVerifier | None" = None):
        self.path = Path(path)
        self._recon = recon_verifier  # trusted, internally configured; NOT a caller callback
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path), timeout=30.0, isolation_level=None)
        # busy_timeout MUST be set before journal_mode: switching to WAL takes a brief
        # exclusive lock and concurrent openers would otherwise fail with "database is locked".
        self._conn.execute("PRAGMA busy_timeout=30000")
        for attempt in range(6):
            try:
                self._conn.execute("PRAGMA journal_mode=WAL")
                break
            except sqlite3.OperationalError:
                if attempt == 5:
                    raise
                time.sleep(0.05 * (attempt + 1))
        self._conn.execute("PRAGMA synchronous=FULL")
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS nonces (
                 nonce TEXT PRIMARY KEY,
                 pccb_id TEXT NOT NULL,
                 effect_id TEXT NOT NULL,
                 state TEXT NOT NULL,
                 reserved_at TEXT NOT NULL,
                 resolved_at TEXT,
                 outcome TEXT,
                 evidence TEXT
               )"""
        )

    def close(self) -> None:
        self._conn.close()

    def get(self, nonce: str) -> NonceRecord | None:
        row = self._conn.execute(
            "SELECT nonce,pccb_id,effect_id,state,reserved_at,resolved_at,outcome FROM nonces WHERE nonce=?",
            (nonce,),
        ).fetchone()
        if not row:
            return None
        return NonceRecord(
            nonce=row[0], pccb_id=row[1], effect_id=row[2], state=row[3],
            reserved_at=row[4], resolved_at=row[5],
            outcome=json.loads(row[6]) if row[6] else None,
        )

    def reserve(self, *, nonce: str, pccb_id: str, effect_id: str) -> NonceRecord:
        """Atomically claim the nonce BEFORE the side effect.

        Refuses replays and blind retries of uncertain outcomes. Of two concurrent
        callers exactly one succeeds (UNIQUE constraint inside BEGIN IMMEDIATE).
        """
        existing = self.get(nonce)
        if existing is not None:
            if existing.state == COMMITTED:
                raise ReplayRefused("NONCE_REUSED", f"nonce {nonce} already committed; refusing duplicate consequential effect", existing.state)
            if existing.state == RESERVED:
                raise ReplayRefused(
                    "UNCERTAIN_OUTCOME",
                    f"nonce {nonce} is reserved with an unresolved outcome (prior attempt may have crashed mid-effect); "
                    "refusing blind retry — reconcile with signed evidence first",
                    existing.state,
                )
            if existing.state == ROLLED_BACK:
                raise ReplayRefused("NONCE_CONSUMED", f"nonce {nonce} was rolled back; single-use nonces are not re-armed", existing.state)
        try:
            self._conn.execute("BEGIN IMMEDIATE")
            self._conn.execute(
                "INSERT INTO nonces(nonce,pccb_id,effect_id,state,reserved_at) VALUES(?,?,?,?,?)",
                (nonce, pccb_id, effect_id, RESERVED, _utcnow()),
            )
            self._conn.execute("COMMIT")
        except sqlite3.IntegrityError:
            self._conn.execute("ROLLBACK")
            raise ReplayRefused("NONCE_RACE_LOST", f"nonce {nonce} was claimed concurrently; this caller lost the atomic claim")
        except Exception:
            try:
                self._conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        rec = self.get(nonce)
        assert rec is not None
        return rec

    def commit(self, *, nonce: str, outcome: dict[str, Any]) -> NonceRecord:
        return self._resolve(nonce, COMMITTED, outcome)

    def rollback(self, *, nonce: str, outcome: dict[str, Any]) -> NonceRecord:
        return self._resolve(nonce, ROLLED_BACK, outcome)

    def reconcile(self, *, nonce: str, resolution: str, evidence: dict[str, Any],
                  resource_id: str) -> NonceRecord:
        """Resolve an UNCERTAIN reserved nonce using cryptographically verified evidence.

        Verification uses the internally-configured trusted ``ReconciliationVerifier`` (pinned
        reconciliation authority) — NEVER a caller-supplied callback, so ``lambda: True`` cannot be
        injected. The statement must bind the exact nonce/pccb/effect/resource/resolution and be
        fresh. Any failure leaves the nonce uncertain (fail closed); the effect is never blind-retried.
        """
        if resolution not in (COMMITTED, ROLLED_BACK):
            raise ValueError("resolution must be 'committed' or 'rolled_back'")
        rec = self.get(nonce)
        if rec is None:
            raise ReplayRefused("NONCE_UNKNOWN", f"cannot reconcile unknown nonce {nonce}")
        if rec.state != RESERVED:
            raise ReplayRefused("RECONCILE_NOT_UNCERTAIN", f"nonce {nonce} is {rec.state}, not uncertain")
        if self._recon is None:
            raise ReplayRefused("RECONCILE_UNAVAILABLE",
                                "no trusted reconciliation verifier configured; nonce stays uncertain (fail closed)")
        if not self._recon.verify(evidence, nonce=nonce, pccb_id=rec.pccb_id, effect_id=rec.effect_id,
                                  resource_id=resource_id, resolution=resolution):
            raise ReplayRefused(
                "RECONCILE_EVIDENCE_INVALID",
                "reconciliation evidence failed cryptographic verification against the pinned reconciliation "
                "trust root (forged, cross-domain, wrong effect, stale, or unknown signer); nonce stays uncertain",
            )
        digest = hashlib.sha256(json.dumps(evidence, sort_keys=True).encode()).hexdigest()
        return self._resolve(nonce, resolution, {"reconciled": True, "evidence_digest": digest})

    def _resolve(self, nonce: str, state: str, outcome: dict[str, Any]) -> NonceRecord:
        cur = self._conn.execute(
            "UPDATE nonces SET state=?, resolved_at=?, outcome=? WHERE nonce=? AND state=?",
            (state, _utcnow(), json.dumps(outcome, sort_keys=True), nonce, RESERVED),
        )
        if cur.rowcount != 1:
            existing = self.get(nonce)
            raise ReplayRefused(
                "RESOLVE_CONFLICT",
                f"nonce {nonce} could not transition to {state} from {existing.state if existing else 'absent'}",
                existing.state if existing else None,
            )
        rec = self.get(nonce)
        assert rec is not None
        return rec

    def uncertain_nonces(self) -> list[NonceRecord]:
        rows = self._conn.execute(
            "SELECT nonce,pccb_id,effect_id,state,reserved_at,resolved_at,outcome FROM nonces WHERE state=?",
            (RESERVED,),
        ).fetchall()
        return [NonceRecord(r[0], r[1], r[2], r[3], r[4], r[5], json.loads(r[6]) if r[6] else None) for r in rows]

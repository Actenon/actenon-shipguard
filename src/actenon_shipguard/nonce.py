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

import json
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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


class NonceStore:
    def __init__(self, path: Path):
        self.path = Path(path)
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

    def reconcile(self, *, nonce: str, resolution: str, evidence: dict[str, Any]) -> NonceRecord:
        """Resolve an UNCERTAIN reserved nonce using signed external evidence.

        ``resolution`` must be 'committed' or 'rolled_back'; ``evidence`` must carry
        a verifier/operator signature establishing whether the external effect really
        occurred. This is the only safe way to clear an uncertain outcome — the side
        effect is never blindly re-run.
        """
        if resolution not in (COMMITTED, ROLLED_BACK):
            raise ValueError("resolution must be 'committed' or 'rolled_back'")
        if not evidence.get("signature") or not evidence.get("established_by"):
            raise ReplayRefused("RECONCILE_EVIDENCE_MISSING", "reconcile requires signed evidence establishing the outcome")
        rec = self.get(nonce)
        if rec is None:
            raise ReplayRefused("NONCE_UNKNOWN", f"cannot reconcile unknown nonce {nonce}")
        return self._resolve(nonce, resolution, {"reconciled": True, **evidence})

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

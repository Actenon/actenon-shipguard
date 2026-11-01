"""Offline deterministic adapter — SEPARATELY LABELLED, no model calls.

This is the preserved regression mode (mandate §7): it applies prewritten candidate
implementations so the orchestrator loop is reproducible in CI without cost or network.
It is explicitly mode="offline-deterministic" and must never be presented as a live
model-generated repair. Attempt 0 applies a plausible-but-wrong fix (the kind that passes
ordinary tests); a repair attempt applies the correct largest-remainder implementation.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from .base import AgentResult, git_diff

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures"
_WRONG = FIXTURES / "candidates" / "arm-a-rounding.ts"     # passes ordinary tests, violates conservation
_CORRECT = FIXTURES / "candidates" / "arm-b-correct.ts"    # largest-remainder, conserves total


class OfflineAdapter:
    name = "offline"
    mode = "offline-deterministic"

    def available(self) -> tuple[bool, str]:
        if _WRONG.exists() and _CORRECT.exists():
            return True, "offline deterministic fixtures present"
        return False, f"offline fixtures missing under {FIXTURES}"

    def propose(self, *, task: str, repo: Path, attempt: int, feedback: str | None,
                timeout: int, target_file: str = "src/settle.ts", export: str = "allocate") -> AgentResult:
        repo = Path(repo)
        ok, reason = self.available()
        if not ok:
            return AgentResult(self.name, self.mode, "unavailable", "", attempt=attempt, error=reason)
        src = _CORRECT if (attempt >= 1 or feedback) else _WRONG
        dest = repo / target_file
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(src, dest)
        changed, diff = git_diff(repo)
        label = "correct largest-remainder fix" if src == _CORRECT else "plausible Math.round fix (wrong)"
        return AgentResult(
            self.name, self.mode, "completed", f"[offline-deterministic] applied prewritten {label}",
            changed or [target_file], diff, attempt, 0.0, None,
            raw={"fixture": src.name, "NOTE": "deterministic regression mode, NOT a live model repair"},
        )

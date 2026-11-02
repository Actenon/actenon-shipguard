"""Agent adapter interface (mandate §7, §15).

A RepairAdapter makes a GENUINE change to a candidate repository in response to a task
and (on later attempts) counterexample feedback. It never reports success on the basis
of "the agent finished without an exception" — the orchestrator independently re-verifies.

Three adapters ship: codex (live, authenticated), claude (live, may be unauthenticated),
and offline (deterministic, separately labelled — the preserved regression mode).
"""
from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol


@dataclass
class AgentResult:
    agent: str                 # codex | claude | offline
    mode: str                  # live | offline-deterministic
    outcome: str               # completed | interrupted | failed | unavailable
    statement: str             # the agent's final message (never treated as proof)
    changed_files: list[str] = field(default_factory=list)
    diff: str = ""
    attempt: int = 0
    duration_s: float = 0.0
    error: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def made_change(self) -> bool:
        return bool(self.changed_files)


class RepairAdapter(Protocol):
    name: str
    mode: str

    def available(self) -> tuple[bool, str]:
        """(usable, reason). An unauthenticated/missing CLI returns (False, reason)."""
        ...

    def propose(self, *, task: str, repo: Path, attempt: int, feedback: str | None,
                timeout: int) -> AgentResult:
        ...


def git_diff(repo: Path) -> tuple[list[str], str]:
    """Return (changed_files, diff) for uncommitted changes in repo."""
    try:
        files = subprocess.run(["git", "-C", str(repo), "diff", "--name-only"],
                               capture_output=True, text=True, timeout=20).stdout.split()
        diff = subprocess.run(["git", "-C", str(repo), "diff"],
                              capture_output=True, text=True, timeout=20).stdout
        # include untracked files the agent may have created
        untracked = subprocess.run(["git", "-C", str(repo), "ls-files", "--others", "--exclude-standard"],
                                   capture_output=True, text=True, timeout=20).stdout.split()
        return sorted(set(files) | set(untracked)), diff
    except Exception:
        return [], ""


def build_prompt(task: str, attempt: int, feedback: str | None, target_file: str, export: str) -> str:
    if attempt == 0 or not feedback:
        return (
            f"{task}\n\n"
            f"Edit only `{target_file}` in this repository. Implement/repair the exported function "
            f"`{export}` so it satisfies the task. Do not modify tests or any other file. "
            f"Make the minimal correct change."
        )
    return (
        f"{task}\n\nA previous attempt did not satisfy an independent requirement.\n\n"
        f"INDEPENDENT VERIFIER COUNTEREXAMPLE:\n{feedback}\n\n"
        f"Repair `{target_file}` (export `{export}`) so this counterexample no longer reproduces, "
        f"without weakening any test or changing files other than `{target_file}`. "
        f"Do not special-case the counterexample input; fix the underlying defect."
    )


def run_bounded(cmd: list[str], cwd: Path, timeout: int) -> tuple[int | None, str, str, bool]:
    """Secure subprocess: bounded timeout, captured output, no shell."""
    start = time.time()
    try:
        p = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True,
                           timeout=timeout, stdin=subprocess.DEVNULL)
        return p.returncode, p.stdout, p.stderr, False
    except subprocess.TimeoutExpired as e:
        return None, (e.stdout or "") if isinstance(e.stdout, str) else "", \
               (e.stderr or "") if isinstance(e.stderr, str) else "", True

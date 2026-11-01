"""Codex CLI adapter (live, real model-generated change).

Invokes `codex exec` non-interactively inside a workspace-write sandbox confined to the
candidate repository, so the agent can edit code but not escape the workspace. The agent's
own statement is captured but NEVER treated as proof — the orchestrator independently
re-verifies via property-verify and the git diff.
"""
from __future__ import annotations

import re
import shutil
import time
from pathlib import Path

from .base import AgentResult, build_prompt, git_diff, run_bounded

_AUTH_FAILURE_MARKERS = (
    "failed to authenticate", "oauth session expired", "not authenticated",
    "login", "unauthorized", "no credentials", "auth",
)


class CodexAdapter:
    name = "codex"
    mode = "live"

    def __init__(self, model: str | None = None, sandbox: str = "workspace-write"):
        self.model = model
        self.sandbox = sandbox

    def available(self) -> tuple[bool, str]:
        if shutil.which("codex") is None:
            return False, "codex CLI not found on PATH"
        return True, "codex CLI present"

    def propose(self, *, task: str, repo: Path, attempt: int, feedback: str | None,
                timeout: int, target_file: str = "src/settle.ts", export: str = "allocate") -> AgentResult:
        repo = Path(repo)
        ok, reason = self.available()
        if not ok:
            return AgentResult(self.name, self.mode, "unavailable", "", attempt=attempt, error=reason)
        prompt = build_prompt(task, attempt, feedback, target_file, export)
        cmd = ["codex", "exec", "--skip-git-repo-check", "--sandbox", self.sandbox, "-C", str(repo)]
        if self.model:
            cmd += ["--model", self.model]
        cmd += [prompt]
        start = time.time()
        code, out, err, timed_out = run_bounded(cmd, repo, timeout)
        dur = round(time.time() - start, 2)
        combined = (out or "") + "\n" + (err or "")
        changed, diff = git_diff(repo)
        statement = _extract_statement(out or "")

        if timed_out:
            return AgentResult(self.name, self.mode, "interrupted", statement, changed, diff,
                               attempt, dur, error=f"timed out after {timeout}s",
                               raw={"exit": code, "stdout_tail": (out or "")[-800:]})
        low = combined.lower()
        if code != 0 and any(m in low for m in _AUTH_FAILURE_MARKERS):
            return AgentResult(self.name, self.mode, "unavailable", statement, changed, diff,
                               attempt, dur, error="codex authentication failed/expired",
                               raw={"exit": code, "stderr_tail": (err or "")[-400:]})
        if code != 0:
            return AgentResult(self.name, self.mode, "failed", statement, changed, diff,
                               attempt, dur, error=f"codex exited {code}",
                               raw={"exit": code, "stderr_tail": (err or "")[-400:]})
        outcome = "completed" if changed else "failed"
        return AgentResult(self.name, self.mode, outcome, statement, changed, diff, attempt, dur,
                           error=None if changed else "agent completed but made no change",
                           raw={"exit": code, "tokens": _extract_tokens(out or "")})


def _extract_statement(out: str) -> str:
    # codex prints the final assistant message after a line containing only "codex"
    blocks = re.split(r"\n(?=codex\n)", out)
    tail = blocks[-1] if blocks else out
    lines = [ln for ln in tail.splitlines() if ln.strip() and not ln.startswith("tokens used")]
    return "\n".join(lines[-12:])[:1200]


def _extract_tokens(out: str) -> str | None:
    m = re.search(r"tokens used\s*\n?\s*(\d+)", out)
    return m.group(1) if m else None

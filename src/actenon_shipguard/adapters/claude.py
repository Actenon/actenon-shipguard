"""Claude Code CLI adapter (live).

Invokes `claude -p` in print mode. Autonomous edits require bypassing interactive
permission prompts; we confine the agent to the candidate repo via cwd + --add-dir and
restrict tools. If the CLI is unauthenticated (e.g. expired OAuth) the adapter reports
`unavailable` with the exact reason — it never fabricates a change or a success.
"""
from __future__ import annotations

import shutil
import time
from pathlib import Path

from .base import AgentResult, build_prompt, git_diff, run_bounded

_AUTH_MARKERS = ("failed to authenticate", "oauth session expired", "could not be refreshed",
                 "not authenticated", "invalid api key", "please run /login", "unauthorized")


class ClaudeAdapter:
    name = "claude"
    mode = "live"

    def __init__(self, model: str | None = None):
        self.model = model

    def available(self) -> tuple[bool, str]:
        if shutil.which("claude") is None:
            return False, "claude CLI not found on PATH"
        return True, "claude CLI present (authentication checked at call time)"

    def propose(self, *, task: str, repo: Path, attempt: int, feedback: str | None,
                timeout: int, target_file: str = "src/settle.ts", export: str = "allocate") -> AgentResult:
        repo = Path(repo)
        ok, reason = self.available()
        if not ok:
            return AgentResult(self.name, self.mode, "unavailable", "", attempt=attempt, error=reason)
        prompt = build_prompt(task, attempt, feedback, target_file, export)
        cmd = ["claude", "-p", prompt, "--output-format", "text",
               "--dangerously-skip-permissions", "--add-dir", str(repo)]
        if self.model:
            cmd += ["--model", self.model]
        start = time.time()
        code, out, err, timed_out = run_bounded(cmd, repo, timeout)
        dur = round(time.time() - start, 2)
        combined = ((out or "") + "\n" + (err or "")).lower()
        changed, diff = git_diff(repo)
        statement = (out or "").strip()[-1200:]

        if timed_out:
            return AgentResult(self.name, self.mode, "interrupted", statement, changed, diff,
                               attempt, dur, error=f"timed out after {timeout}s")
        if any(m in combined for m in _AUTH_MARKERS):
            return AgentResult(self.name, self.mode, "unavailable", statement, changed, diff,
                               attempt, dur, error="claude authentication failed/expired (OAuth)",
                               raw={"exit": code, "stderr_tail": (err or "")[-400:]})
        if code != 0:
            return AgentResult(self.name, self.mode, "failed", statement, changed, diff,
                               attempt, dur, error=f"claude exited {code}",
                               raw={"exit": code, "stderr_tail": (err or "")[-400:]})
        outcome = "completed" if changed else "failed"
        return AgentResult(self.name, self.mode, outcome, statement, changed, diff, attempt, dur,
                           error=None if changed else "agent completed but made no change")

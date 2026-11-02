"""Claude Code CLI adapter (live) — SECURED.

Security posture (mandate §SECOND):
  * ``--dangerously-skip-permissions`` is REMOVED. Autonomous edits use the supported
    ``--permission-mode acceptEdits`` plus an explicit ``--allowedTools`` allowlist (file
    tools only) and a ``--disallowedTools`` denylist (no shell, no web) — never a blanket
    permission bypass.
  * Live execution is gated behind TWO conditions: an explicit operator consent env var
    (``SHIPGUARD_ENABLE_LIVE_CLAUDE=1``) AND a successful authentication probe. cwd/``--add-dir``
    are NOT treated as isolation; the supported permission controls are.
  * If the CLI is missing, unauthenticated (e.g. expired OAuth), or not consented, the adapter
    reports ``unavailable`` with the exact reason — it NEVER fabricates a change or a success.

NOTE: in the current development environment Claude OAuth is expired, so ``available()`` returns
False and live Claude execution is honestly disabled. Codex is the authenticated live provider.
"""
from __future__ import annotations

import os
import shutil
import time
from pathlib import Path

from .base import AgentResult, build_prompt, git_diff, run_bounded

_AUTH_MARKERS = ("failed to authenticate", "oauth session expired", "could not be refreshed",
                 "not authenticated", "invalid api key", "please run /login", "unauthorized")

# Supported, narrow tool controls — file edits only, no shell, no network tools.
_ALLOWED_TOOLS = ["Read", "Edit", "Write"]
_DISALLOWED_TOOLS = ["Bash", "WebFetch", "WebSearch", "NotebookEdit"]


class ClaudeAdapter:
    name = "claude"
    mode = "live"

    def __init__(self, model: str | None = None):
        self.model = model

    def available(self) -> tuple[bool, str]:
        if shutil.which("claude") is None:
            return False, "claude CLI not found on PATH"
        # Execution consent: live Claude is off by default until an operator has reviewed the
        # confinement (permission-mode + allowed/disallowed tools) and credential exposure.
        if os.environ.get("SHIPGUARD_ENABLE_LIVE_CLAUDE") != "1":
            return False, ("live Claude execution disabled by default — --dangerously-skip-permissions "
                           "was removed and the supported permission-mode/allowedTools confinement has "
                           "not been validated by a live run here. Set SHIPGUARD_ENABLE_LIVE_CLAUDE=1 "
                           "only after reviewing confinement + credential exposure.")
        # Bounded authentication probe (cheap; fails fast when OAuth is expired).
        code, out, err, timed_out = run_bounded(
            ["claude", "-p", "Reply with the single word OK.", "--output-format", "text"],
            Path.cwd(), 40)
        combined = ((out or "") + "\n" + (err or "")).lower()
        if timed_out or any(m in combined for m in _AUTH_MARKERS):
            return False, "claude authentication failed/expired (OAuth) — live execution disabled"
        return True, "claude CLI present, authenticated, and live execution consented"

    def propose(self, *, task: str, repo: Path, attempt: int, feedback: str | None,
                timeout: int, target_file: str = "src/settle.ts", export: str = "allocate") -> AgentResult:
        repo = Path(repo)
        ok, reason = self.available()
        if not ok:
            return AgentResult(self.name, self.mode, "unavailable", "", attempt=attempt, error=reason)
        prompt = build_prompt(task, attempt, feedback, target_file, export)
        # NO --dangerously-skip-permissions. Supported permission mode + explicit tool allowlist.
        cmd = ["claude", "-p", prompt, "--output-format", "text",
               "--permission-mode", "acceptEdits",
               "--allowedTools", *_ALLOWED_TOOLS,
               "--disallowedTools", *_DISALLOWED_TOOLS]
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

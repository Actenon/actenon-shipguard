"""Adapter safety tests (mandate §SECOND) — hermetic, no live model calls.

These lock in the security posture of the agent adapters:
  * Claude never uses --dangerously-skip-permissions; it uses supported permission-mode +
    an explicit tool allowlist/denylist, and is gated behind consent + auth.
  * Codex uses the supported workspace-write sandbox, never the bypass flag, and probes auth.
  * A disabled/unauthenticated adapter reports `unavailable` and NEVER fabricates a change.
  * The offline adapter is explicitly labelled offline-deterministic.
"""
from __future__ import annotations

import actenon_shipguard.adapters.claude as claude_mod
import actenon_shipguard.adapters.codex as codex_mod
from actenon_shipguard.adapters.claude import ClaudeAdapter
from actenon_shipguard.adapters.codex import CodexAdapter
from actenon_shipguard.adapters.offline import OfflineAdapter


def test_claude_disabled_without_consent_does_not_fabricate(tmp_path, monkeypatch):
    monkeypatch.delenv("SHIPGUARD_ENABLE_LIVE_CLAUDE", raising=False)
    called = {"n": 0}

    def _no_exec(cmd, cwd, timeout):           # must never even reach a model call
        called["n"] += 1
        return 0, "", "", False

    monkeypatch.setattr(claude_mod, "run_bounded", _no_exec)
    r = ClaudeAdapter().propose(task="t", repo=tmp_path, attempt=0, feedback=None, timeout=5)
    assert r.outcome == "unavailable" and not r.made_change
    # available() short-circuits on consent, so the only run_bounded call is the auth probe at most;
    # critically, no edit was fabricated.
    assert r.error and "disabled" in r.error


def test_claude_command_uses_supported_controls_not_dangerous_flag(tmp_path, monkeypatch):
    monkeypatch.setenv("SHIPGUARD_ENABLE_LIVE_CLAUDE", "1")
    cmds: list[list[str]] = []

    def _capture(cmd, cwd, timeout):
        cmds.append(list(cmd))
        return 0, "OK", "", False              # auth probe + propose both "succeed"

    monkeypatch.setattr(claude_mod, "run_bounded", _capture)
    ClaudeAdapter().propose(task="fix the bug", repo=tmp_path, attempt=0, feedback=None, timeout=5)
    propose = next(c for c in cmds if "--permission-mode" in c)
    assert "--dangerously-skip-permissions" not in propose
    assert "acceptEdits" in propose
    assert "--allowedTools" in propose and "--disallowedTools" in propose
    disallowed = propose[propose.index("--disallowedTools") + 1:]
    assert "Bash" in disallowed                 # no shell for the coding agent


def test_codex_uses_workspace_write_sandbox_never_bypass(tmp_path, monkeypatch):
    cmds: list[list[str]] = []

    def _capture(cmd, cwd, timeout):
        cmds.append(list(cmd))
        if "login" in cmd and "status" in cmd:
            return 0, "Logged in using ChatGPT", "", False
        return 0, "done", "", False

    monkeypatch.setattr(codex_mod, "run_bounded", _capture)
    CodexAdapter().propose(task="fix the bug", repo=tmp_path, attempt=0, feedback=None, timeout=5)
    exec_cmd = next(c for c in cmds if "exec" in c)
    assert "--dangerously-bypass-approvals-and-sandbox" not in exec_cmd
    assert "--sandbox" in exec_cmd and "workspace-write" in exec_cmd


def test_codex_unauthenticated_is_unavailable(tmp_path, monkeypatch):
    def _no_auth(cmd, cwd, timeout):
        return 1, "", "not logged in", False

    monkeypatch.setattr(codex_mod, "run_bounded", _no_auth)
    ok, reason = CodexAdapter().available()
    assert ok is False and "NOT authenticated" in reason


def test_offline_adapter_is_labelled_deterministic(tmp_path):
    a = OfflineAdapter()
    assert a.mode == "offline-deterministic"
    ok, _ = a.available()
    assert ok is True
    r = a.propose(task="t", repo=tmp_path, attempt=0, feedback=None, timeout=5)
    assert r.mode == "offline-deterministic"
    assert "NOT a live model repair" in (r.raw.get("NOTE", "") + r.statement)

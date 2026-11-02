"""Phase 2 — safe mode against real developer repositories.

Proves: the project is inspected and unsupported types rejected clearly; work happens in a disposable
isolated clone; the developer's original tree and Git history are never modified (verified by
fingerprint, not by promise); the project's OWN test script is used; and the approved contract is
immutable during execution.

A scripted adapter stands in for the coding agent so these mechanics are testable deterministically
without model calls. It is labelled offline-deterministic and is NOT a live model repair.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

import actenon_shipguard as _sg
from actenon_shipguard.adapters.base import AgentResult, git_diff
from actenon_shipguard.orchestrator import (
    _commit_candidate, clone_isolated, inspect_project, repo_fingerprint, run_task,
)
from actenon_shipguard.sentinel import find_sentinel

_PKG_DIR = Path(_sg.__file__).resolve().parent
FIXTURES = _PKG_DIR / "_bundled"
CONTRACT = json.loads((FIXTURES / "contracts" / "settlement-contract.json").read_text())
MODULE = "src/settle.ts"
SENTINEL = find_sentinel()


def _resolve_nm():
    import os
    env = os.environ.get("SHIPGUARD_NODE_MODULES")
    cands = ([Path(env)] if env else []) + [
        Path(__file__).resolve().parents[3] / "sentinel-verified" / "node_modules",
        Path(__file__).resolve().parents[2] / "sentinel-verified" / "node_modules"]
    return next((p for p in cands if (p / ".bin" / "vitest").exists()), None)


NODE_MODULES = _resolve_nm()
needs_sentinel = pytest.mark.skipif(SENTINEL is None or NODE_MODULES is None,
                                    reason="real sentinel CLI or node_modules(vitest) unavailable")


class ScriptedAdapter:
    """Deterministic stand-in for a coding agent: applies given source bytes per attempt."""

    name = "scripted"
    mode = "offline-deterministic"

    def __init__(self, sources: list[bytes]):
        self.sources = sources

    def available(self) -> tuple[bool, str]:
        return True, "scripted test adapter"

    def propose(self, *, task, repo, attempt, feedback, timeout,
                target_file=MODULE, export="allocate") -> AgentResult:
        repo = Path(repo)
        (repo / target_file).write_bytes(self.sources[min(attempt, len(self.sources) - 1)])
        changed, diff = git_diff(repo)
        return AgentResult(self.name, self.mode, "completed",
                           "[scripted] applied prewritten source (test adapter)",
                           changed or [target_file], diff, attempt, 0.0, None,
                           raw={"NOTE": "deterministic test adapter, NOT a live model repair"})


def _make_real_repo(dest: Path, *, with_package_json: bool = True, with_tests: bool = True,
                    gitignore: str = "node_modules\n", real_node_modules: bool = False) -> Path:
    """Construct a small but genuine developer repository with Git history and its own tests."""
    (dest / "src").mkdir(parents=True, exist_ok=True)
    shutil.copy(FIXTURES / "candidates" / "baseline-buggy.ts", dest / MODULE)
    if with_tests:
        shutil.copy(FIXTURES / "target-settlement" / "src" / "settle.test.ts", dest / "src" / "settle.test.ts")
    if with_package_json:
        (dest / "package.json").write_text(json.dumps(
            {"name": "payments-ledger", "private": True, "type": "module",
             "scripts": {"test": "vitest run"}}))
    (dest / ".gitignore").write_text(gitignore)
    if real_node_modules:            # what a genuine local install looks like: a real directory
        (dest / "node_modules" / ".keep").parent.mkdir(parents=True)
        (dest / "node_modules" / ".keep").write_text("")
    else:
        (dest / "node_modules").symlink_to(NODE_MODULES, target_is_directory=True)
    for a in (["init", "-q"], ["config", "user.email", "dev@example.com"], ["config", "user.name", "dev"],
              ["add", "-A"], ["commit", "-qm", "initial commit: settlement service"],
              ["commit", "--allow-empty", "-qm", "chore: add CI config"]):
        subprocess.run(["git", "-C", str(dest), *a], check=True, capture_output=True)
    return dest


# --------------------------------------------------------------------------- #
# Project inspection: supported vs clearly-rejected
# --------------------------------------------------------------------------- #
def test_inspect_project_accepts_a_supported_repo(tmp_path):
    repo = _make_real_repo(tmp_path / "proj")
    info = inspect_project(repo, MODULE, "allocate")
    assert info["supported"] is True, info["problems"]
    assert info["test_script"] == "vitest run" and info["package_name"] == "payments-ledger"


def test_inspect_project_rejects_non_js_project(tmp_path):
    d = tmp_path / "notjs"; d.mkdir()
    (d / "main.py").write_text("print('hi')\n")
    subprocess.run(["git", "-C", str(d), "init", "-q"], check=True)
    info = inspect_project(d, "main.py", "main")
    assert info["supported"] is False
    assert any("package.json" in p for p in info["problems"])


def test_inspect_project_rejects_missing_export_and_module(tmp_path):
    repo = _make_real_repo(tmp_path / "proj")
    assert any("does not exist" in p for p in inspect_project(repo, "src/nope.ts", "allocate")["problems"])
    assert any("does not export" in p for p in inspect_project(repo, MODULE, "notAFunction")["problems"])


def test_inspect_project_rejects_no_test_script(tmp_path):
    repo = _make_real_repo(tmp_path / "proj")
    (repo / "package.json").write_text(json.dumps({"name": "x", "private": True, "type": "module"}))
    info = inspect_project(repo, MODULE, "allocate")
    assert info["supported"] is False
    assert any("test" in p and "script" in p for p in info["problems"])


def test_clone_isolated_does_not_touch_the_original(tmp_path):
    repo = _make_real_repo(tmp_path / "proj")
    before = repo_fingerprint(repo)
    clone = clone_isolated(repo, tmp_path / "work", NODE_MODULES)
    assert clone != repo and clone.exists()
    assert repo_fingerprint(repo) == before                      # original untouched
    # history is preserved in the isolated copy
    log = subprocess.run(["git", "-C", str(clone), "log", "--oneline"], capture_output=True,
                         text=True, check=True).stdout.strip().splitlines()
    assert len(log) == 2 and "initial commit" in log[-1]
    assert (clone / "node_modules").exists()


def test_clone_isolated_keeps_symlinked_node_modules_untracked_even_with_slashed_gitignore(tmp_path):
    """`node_modules/` does not match a symlink, and Sentinel rejects a tracked node_modules entry.

    Real repositories commonly ignore `node_modules/` with a trailing slash. The isolated clone must
    still keep the shared dependency symlink out of Git — without rewriting any tracked file.
    """
    repo = _make_real_repo(tmp_path / "proj", gitignore="dist\nnode_modules/\n",
                           real_node_modules=True)
    before = repo_fingerprint(repo)
    clone = clone_isolated(repo, tmp_path / "work", NODE_MODULES)

    assert (clone / "node_modules").is_symlink()
    tracked = subprocess.run(["git", "-C", str(clone), "ls-files"], capture_output=True,
                             text=True, check=True).stdout.split()
    assert not [f for f in tracked if f.split("/")[0] == "node_modules"], tracked
    status = subprocess.run(["git", "-C", str(clone), "status", "--porcelain"], capture_output=True,
                            text=True, check=True).stdout.strip()
    assert status == "", f"the dependency symlink leaked into the working tree: {status}"
    # the fix is local to the clone: the developer's own .gitignore is untouched
    assert (repo / ".gitignore").read_text() == "dist\nnode_modules/\n"
    assert (clone / ".gitignore").read_text() == "dist\nnode_modules/\n"
    assert repo_fingerprint(repo) == before


# --------------------------------------------------------------------------- #
# End-to-end real-repository run
# --------------------------------------------------------------------------- #
@pytest.mark.sentinel_integration
@needs_sentinel
def test_real_repo_run_verifies_in_an_isolated_clone(tmp_path):
    proj = _make_real_repo(tmp_path / "proj")
    before = repo_fingerprint(proj)
    contract = tmp_path / "approved-contract.json"          # held out, OUTSIDE the repo
    contract.write_text(json.dumps(CONTRACT))

    rec = run_task(task="Conserve every penny when splitting a whole-pence total across N parties.",
                   adapter=ScriptedAdapter([(FIXTURES / "candidates" / "arm-a-rounding.ts").read_bytes(),
                                            (FIXTURES / "candidates" / "arm-b-correct.ts").read_bytes()]),
                   work=tmp_path / "work", sentinel_cli=SENTINEL, approved_contract=contract,
                   node_modules=NODE_MODULES, max_attempts=1, runner="local",
                   evidence_dir=tmp_path / "evidence", source_repo=proj,
                   target_file=MODULE, export="allocate")

    assert rec.final_status == "verified", rec.states
    assert "PROJECT_INSPECTION" in rec.states and "ORIGINAL_TREE_CHECK" in rec.states
    # The developer's repository was never modified: same HEAD, clean, identical tracked content.
    assert rec.original_untouched is True
    assert repo_fingerprint(proj) == before
    assert rec.source_fingerprint_before == rec.source_fingerprint_after
    # Real independent verification with the aspirin demonstrated on a real project layout.
    assert rec.ordinary_tests_green_on_defect is True
    verdicts = [a["challenge"]["verdict"] for a in rec.attempts]
    assert verdicts[0] == "CONTRADICTED" and verdicts[-1] == "VERIFIED"
    # The project's OWN test script was used.
    assert rec.attempts[0]["ordinary_tests"]["runner"] == "npm-test"
    # Committed tree in the clone is byte-identical to what Sentinel verified.
    assert rec.tree_binding and rec.tree_binding["equivalent"] is True


@pytest.mark.sentinel_integration
@needs_sentinel
def test_real_repo_run_rejects_unsupported_project(tmp_path):
    d = tmp_path / "unsupported"; d.mkdir()
    (d / "main.py").write_text("print('hi')\n")
    subprocess.run(["git", "-C", str(d), "init", "-q"], check=True)
    contract = tmp_path / "c.json"; contract.write_text(json.dumps(CONTRACT))
    rec = run_task(task="do something", adapter=ScriptedAdapter([b"x"]), work=tmp_path / "work",
                   sentinel_cli=SENTINEL, approved_contract=contract, node_modules=NODE_MODULES,
                   max_attempts=0, runner="local", evidence_dir=tmp_path / "ev",
                   source_repo=d, target_file="main.py", export="main")
    assert rec.final_status == "environment_failure"
    assert "UNSUPPORTED_PROJECT" in rec.states
    assert rec.original_untouched is None or rec.original_untouched is True


@pytest.mark.sentinel_integration
@needs_sentinel
def test_contract_is_immutable_during_execution(tmp_path):
    """A mutable contract would let the agent redefine acceptance; the digest guard must hold."""
    proj = _make_real_repo(tmp_path / "proj")
    contract = tmp_path / "approved-contract.json"
    contract.write_text(json.dumps(CONTRACT))

    class TamperingAdapter(ScriptedAdapter):
        def propose(self, **kw):
            contract.write_text(json.dumps({**CONTRACT, "requirements": []}))   # redefine acceptance
            return super().propose(**kw)

    rec = run_task(task="conserve pennies", adapter=TamperingAdapter([b"export function allocate(){return []}\n"]),
                   work=tmp_path / "work", sentinel_cli=SENTINEL, approved_contract=contract,
                   node_modules=NODE_MODULES, max_attempts=0, runner="local",
                   evidence_dir=tmp_path / "ev", source_repo=proj, target_file=MODULE, export="allocate")
    assert rec.final_status == "review_required"
    assert "TAMPER" in rec.states


def test_clone_isolated_can_commit_without_any_global_git_identity(tmp_path, monkeypatch):
    """A clone does not inherit the source repo's local git config.

    CI runners and freshly provisioned machines often have no global `user.email`/`user.name`, and
    committing the verified candidate then dies with exit 128 — which is how this was caught. The
    isolated clone must carry its own identity so safe mode does not depend on the host's git config.
    """
    empty_home = tmp_path / "no-home"
    empty_home.mkdir()
    monkeypatch.setenv("HOME", str(empty_home))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/dev/null")
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", "/dev/null")

    repo = _make_real_repo(tmp_path / "proj")           # sets its own LOCAL identity
    before = repo_fingerprint(repo)
    clone = clone_isolated(repo, tmp_path / "work", NODE_MODULES)

    ident = subprocess.run(["git", "-C", str(clone), "config", "user.email"],
                           capture_output=True, text=True, check=True).stdout.strip()
    assert ident, "the isolated clone has no commit identity of its own"

    (clone / MODULE).write_text((clone / MODULE).read_text() + "\n// verified repair\n")
    head = _commit_candidate(clone, "verified change", [MODULE])
    assert re.fullmatch(r"[0-9a-f]{40}", head), head
    author = subprocess.run(["git", "-C", str(clone), "log", "-1", "--format=%an <%ae>"],
                            capture_output=True, text=True, check=True).stdout.strip()
    assert "ShipGuard" in author, f"the commit must be attributed to ShipGuard, not the developer: {author}"
    # the developer's repository never gained a commit or a config change
    assert repo_fingerprint(repo) == before
    assert subprocess.run(["git", "-C", str(repo), "log", "--oneline"], capture_output=True,
                          text=True, check=True).stdout.count("\n") == 2

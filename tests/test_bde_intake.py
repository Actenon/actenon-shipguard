"""Negative host-intake controls; synthetic, never holdout defects."""
import argparse
import os
import subprocess

import pytest

from actenon_shipguard.bde.intake import (
    MAX_EVIDENCE_BYTES,
    IntakeRefused,
    copy_tracked_overlay,
    read_evidence,
)
from actenon_shipguard.bde.sources import collect


@pytest.fixture
def source(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "index.ts").write_text("export function identity(value: string) { return value; }")
    return repo


@pytest.mark.parametrize("entry", ["README.md", "package.json", "index.ts", "index.test.ts"])
def test_collector_refuses_external_symlink_without_reading_canary(source, tmp_path, entry):
    secret = tmp_path / "outside.txt"
    secret.write_text('HOST_CANARY_MUST_NOT_ENTER_EVIDENCE')
    target = source / entry
    target.unlink(missing_ok=True)
    target.symlink_to(secret)
    with pytest.raises(IntakeRefused) as caught:
        collect(source, "index.ts", "synthetic")
    assert "HOST_CANARY" not in str(caught.value)


def test_ancestor_symlink_and_traversal_are_refused(source, tmp_path):
    external = tmp_path / "private"
    external.mkdir()
    (external / "file.ts").write_text("canary")
    (source / "linked").symlink_to(external, target_is_directory=True)
    for path in ("linked/file.ts", "../private/file.ts", str(external / "file.ts"), ".git/config"):
        with pytest.raises(IntakeRefused):
            read_evidence(source, path)


def test_special_and_oversized_evidence_fail_closed(source):
    os.mkfifo(source / "pipe")
    with pytest.raises(IntakeRefused):
        read_evidence(source, "pipe")
    (source / "large").write_bytes(b"x" * (MAX_EVIDENCE_BYTES + 1))
    with pytest.raises(IntakeRefused):
        read_evidence(source, "large")
    assert read_evidence(source, "index.ts").startswith("export function identity")


@pytest.mark.parametrize("runner", ["local", "docker"])
def test_no_intake_consent_refuses_before_git_or_collection(source, tmp_path, monkeypatch, runner):
    import actenon_shipguard.bde.check as check
    monkeypatch.delenv("SHIPGUARD_ALLOW_LOCAL", raising=False)
    def forbidden(*args, **kwargs):
        pytest.fail("unconsented intake reached Git or source collection")
    monkeypatch.setattr(check, "repo_fingerprint", forbidden)
    monkeypatch.setattr(check, "clone_isolated", forbidden)
    monkeypatch.setattr(check, "collect", forbidden)
    result = check.run_bde(source, module="index.ts", runner=runner, out_dir=tmp_path / "out")
    assert result.overall_status == "ENVIRONMENT_FAILURE"
    assert result.executed == 0 and not result.findings
    assert "host intake consent" in result.not_checked[0]["reason"]


def test_docker_reproduction_refuses_before_loading_evidence(monkeypatch):
    import actenon_shipguard.cli as cli
    def forbidden(*args, **kwargs):
        pytest.fail("unconsented reproduction loaded evidence")
    monkeypatch.setattr(cli, "_load_evidence", forbidden)
    assert cli.cmd_reproduce(argparse.Namespace(runner="docker", allow_host_intake=False)) == 2


def test_overlay_cannot_read_or_overwrite_external_canary(source, tmp_path):
    clone = tmp_path / "clone"
    clone.mkdir()
    secret = tmp_path / "canary"
    secret.write_text("unchanged-canary")
    (source / "README.md").symlink_to(secret)
    with pytest.raises(IntakeRefused):
        copy_tracked_overlay(source, clone, "README.md")
    assert not (clone / "README.md").exists()
    (source / "README.md").unlink()
    (source / "README.md").write_text("ordinary source")
    (clone / "README.md").symlink_to(secret)
    with pytest.raises(IntakeRefused):
        copy_tracked_overlay(source, clone, "README.md")
    assert secret.read_text() == "unchanged-canary"


def test_committed_readme_link_fails_before_law_compilation(source, tmp_path):
    from actenon_shipguard.bde.check import run_bde
    canary = tmp_path / "private.md"
    canary.write_text("HOST_CANARY_MUST_NOT_ENTER_LAWS")
    (source / "README.md").symlink_to(canary)
    for command in (["init", "-q"], ["add", "-A"],
                    ["-c", "user.name=control", "-c", "user.email=control@example.invalid",
                     "-c", "commit.gpgsign=false", "commit", "-qm", "Synthetic intake control"]):
        subprocess.run(["git", *command], cwd=source, check=True, capture_output=True)
    result = run_bde(source, module="index.ts", runner="docker", allow_host_intake=True,
                     out_dir=tmp_path / "out")
    assert result.overall_status == "ENVIRONMENT_FAILURE"
    assert result.laws_total == result.executed == 0 and not result.findings
    assert "HOST_CANARY" not in str(result)
    assert canary.read_text() == "HOST_CANARY_MUST_NOT_ENTER_LAWS"

"""Independent negative probes of the actual Docker boundary, not command mocks."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from actenon_shipguard.bde.scheduler import run_lawpack

pytestmark = pytest.mark.bde_containment


@pytest.fixture
def image():
    value = os.environ.get("SHIPGUARD_BDE_IMAGE")
    assert value, "mandatory containment tests require SHIPGUARD_BDE_IMAGE; never silently skip"
    return value


def execute(tmp_path: Path, image: str, source: str, **limits):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "package.json").write_text('{"type":"module"}')
    (repo / "index.ts").write_text(source)
    pack = {"schema_version": 1, "module": "index.ts", "git_revision": "control",
            "laws": [{"law_id": "probe", "predicate": "example_executable", "export": "probe",
                      "params": {"expected": True},
                      "gen": {"mode": "literal", "args": [], "shrink": False}}]}
    return run_lawpack(pack, repo, None, runner="docker", image=image, **limits)


def test_no_network_credentials_or_host_write(tmp_path, image, monkeypatch):
    monkeypatch.setenv("SHIPGUARD_TEST_HOST_SECRET", "must-not-enter-container")
    source = '''
import fs from 'node:fs';
import {execFileSync} from 'node:child_process';
export function probe() {
 const writes = ['/target/index.ts', '/engine/runner.mjs', '/root/escape'];
 for (const p of writes) { try { fs.writeFileSync(p, 'escape'); return false; } catch {} }
 if (process.getuid() === 0 || process.env.SHIPGUARD_TEST_HOST_SECRET) return false;
 if (fs.existsSync('/var/run/docker.sock') || fs.existsSync('/Users/ross/.codex/auth.json')) return false;
 try {
  execFileSync(process.execPath, ['-e', "fetch('https://example.com',{signal:AbortSignal.timeout(1000)}).then(()=>process.exit(0),()=>process.exit(7))"], {timeout:2000});
  return false;
 } catch {}
 return fs.readFileSync('/sys/fs/cgroup/pids.max','utf8').trim() === '64'
  && fs.readFileSync('/sys/fs/cgroup/memory.max','utf8').trim() === '268435456';
}
'''
    before = source
    report = execute(tmp_path, image, source, per_law_ms=5000, timeout_s=15)
    assert (report.passed, report.errors) == (1, 0), report
    assert (tmp_path / "repo/index.ts").read_text() == before


def test_output_flood_is_killed_without_unbounded_capture(tmp_path, image):
    report = execute(tmp_path, image,
                     "import {writeSync} from 'node:fs'; export function probe() { while(true) writeSync(1,'x'.repeat(65536)); }",
                     per_law_ms=5000, timeout_s=10, max_output_bytes=100000)
    assert report.runner_error and "output exceeded" in report.runner_error, report
    assert report.findings == []


def test_wall_timeout_kills_detached_children(tmp_path, image):
    report = execute(tmp_path, image,
                     "import {spawn} from 'node:child_process'; export function probe() { "
                     "spawn(process.execPath, ['-e','setInterval(()=>{},1000)'], {detached:true,stdio:'ignore'}).unref(); "
                     "while(true) {} }", per_law_ms=10000, timeout_s=2)
    assert report.runner_error and "exceeded" in report.runner_error, report
    live = subprocess.run(["docker", "ps", "-q", "--filter", "name=shipguard-bde-"],
                          capture_output=True, text=True, check=True)
    assert not live.stdout.strip(), "a container or its children survived cleanup"


def test_memory_exhaustion_is_environment_failure(tmp_path, image):
    report = execute(tmp_path, image,
                     "export function probe() { const xs=[]; while(true) xs.push(Buffer.alloc(8*1024*1024,1)); }",
                     per_law_ms=10000, timeout_s=15)
    assert report.errors or report.runner_error, report
    assert report.findings == []


def test_pid_exhaustion_is_refused(tmp_path, image):
    report = execute(tmp_path, image, '''
import {spawnSync} from 'node:child_process';
export function probe() {
 const code = "import {spawn} from 'node:child_process'; let denied=false; for(let i=0;i<200;i++){ const p=spawn('/bin/sleep',['2']); p.on('error',()=>{denied=true}); } setTimeout(()=>process.exit(denied?0:1),1000)";
 const result=spawnSync(process.execPath,['--input-type=module','-e',code],{timeout:5000});
 return result.status === 0;
}
''', per_law_ms=7000, timeout_s=12)
    assert report.passed == 1, report


def test_unpinned_image_fails_closed(tmp_path):
    report = execute(tmp_path, "node:latest", "export function probe(){return true;}")
    assert report.runner_error and "immutable" in report.runner_error
    assert report.executed == 0

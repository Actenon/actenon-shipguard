"""Bounded subprocess capture and an opt-in, fail-closed Docker execution boundary.

The Docker daemon/kernel are trusted. This is containment of target code, not an
independent semantic oracle or a claim of immunity from container escape.
"""
from __future__ import annotations

import os
import re
import selectors
import signal
import subprocess
import time
from pathlib import Path


class ExecutionLimitError(RuntimeError):
    pass


def bounded_run(command: list[str], *, timeout_s: float, max_output_bytes: int = 4_000_000) -> subprocess.CompletedProcess:
    """Capture a bounded amount of stdout+stderr and kill the process group on failure."""
    proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            start_new_session=True)
    buffers = {"stdout": bytearray(), "stderr": bytearray()}
    deadline = time.monotonic() + timeout_s
    total = 0
    try:
        with selectors.DefaultSelector() as selector:
            for name in buffers:
                selector.register(getattr(proc, name), selectors.EVENT_READ, name)
            while selector.get_map():
                if time.monotonic() >= deadline:
                    raise ExecutionLimitError(f"execution exceeded {timeout_s}s")
                for key, _ in selector.select(timeout=min(0.2, max(0, deadline - time.monotonic()))):
                    chunk = os.read(key.fileobj.fileno(), 65536)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    total += len(chunk)
                    if total > max_output_bytes:
                        raise ExecutionLimitError(f"output exceeded {max_output_bytes} bytes")
                    buffers[key.data].extend(chunk)
            code = proc.wait(timeout=max(0.01, deadline - time.monotonic()))
        return subprocess.CompletedProcess(command, code,
                                           buffers["stdout"].decode(errors="replace"),
                                           buffers["stderr"].decode(errors="replace"))
    finally:
        # Also close children holding inherited pipes after their parent exits.
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.wait(timeout=5)
        proc.stdout.close()
        proc.stderr.close()


def docker_command(*, image: str, name: str, repo: Path, pack: Path,
                   runner: Path, per_law_ms: int) -> list[str]:
    if not re.fullmatch(r"(?:sha256:|[A-Za-z0-9._/:-]+@sha256:)[0-9a-f]{64}", image):
        raise ValueError("Docker execution requires an immutable image SHA-256 digest (SHIPGUARD_BDE_IMAGE)")
    mounts = [(repo.resolve(), "/target"), (pack.resolve(), "/input/laws.json"),
              (runner.resolve(), "/engine/runner.mjs")]
    if any("," in str(path) for path, _ in mounts):
        raise ValueError("Docker bind paths containing commas are unsupported")
    command = ["docker", "run", "--rm", "--pull", "never", "--name", name,
               "--network", "none", "--read-only", "--user", "65534:65534",
               "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
               "--pids-limit", "64", "--memory", "256m", "--memory-swap", "256m",
               "--cpus", "1", "--ulimit", "nofile=256:256",
               "--tmpfs", "/tmp:rw,noexec,nosuid,size=32m", "--workdir", "/target"]
    for path, target in mounts:
        command += ["--mount", f"type=bind,source={path},target={target},readonly"]
    command += ["--entrypoint", "/runtime/node_modules/.bin/tsx", image,
                "/engine/runner.mjs", "--tsx", "/runtime/node_modules/.bin/tsx",
                "--lawpack", "/input/laws.json", "--repo", "/target",
                "--per-law-ms", str(per_law_ms)]
    return command

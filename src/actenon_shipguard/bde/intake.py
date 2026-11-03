"""Bound collector reads; this does not sandbox Git or make hostile intake safe."""
from __future__ import annotations

import os
import stat
from pathlib import Path

MAX_EVIDENCE_BYTES = 4 * 1024 * 1024


class IntakeRefused(ValueError):
    pass


def relative_parts(path: str | Path) -> tuple[str, ...]:
    value = Path(path)
    if value.is_absolute() or not value.parts or any(p in ("..", ".git") for p in value.parts):
        raise IntakeRefused("evidence paths must stay inside the repository and outside Git metadata")
    return value.parts


def read_evidence_bytes(repo: Path, relative: str | Path) -> bytes:
    """Read a bounded regular file without following final or ancestor symlinks.

    Descriptor-relative traversal also avoids a check/read symlink race. A trusted
    repository root and Git configuration are still required by the calling CLI.
    """
    parts = relative_parts(relative)
    descriptors: list[int] = []
    try:
        current = os.open(repo, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        descriptors.append(current)
        for part in parts[:-1]:
            current = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=current)
            descriptors.append(current)
        fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=current)
        descriptors.append(fd)
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_EVIDENCE_BYTES:
            raise IntakeRefused("evidence must be a regular file no larger than 4 MiB")
        chunks: list[bytes] = []
        size = 0
        while True:
            chunk = os.read(fd, min(65536, MAX_EVIDENCE_BYTES + 1 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
            if size > MAX_EVIDENCE_BYTES:
                raise IntakeRefused("evidence exceeded the 4 MiB read limit")
        return b"".join(chunks)
    except OSError as exc:
        raise IntakeRefused("evidence read refused: missing, linked or inaccessible repository file") from exc
    finally:
        for fd in reversed(descriptors):
            os.close(fd)


def read_evidence(repo: Path, relative: str | Path) -> str:
    return read_evidence_bytes(repo, relative).decode("utf-8", errors="replace")


def copy_tracked_overlay(source: Path, clone: Path, relative: str) -> None:
    """Copy into our disposable clone without following source or clone links."""
    parts = relative_parts(relative)
    data = read_evidence_bytes(source, relative)
    destination = clone
    for part in parts:
        destination = destination / part
        if destination.is_symlink():
            raise IntakeRefused("tracked overlay cannot replace or traverse a symlink")
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o644)
    with os.fdopen(fd, "wb") as output:
        output.write(data)
    # Only the disposable clone is changed, before target code can execute.
    destination.chmod(0o755 if (source / relative).stat().st_mode & 0o111 else 0o644)

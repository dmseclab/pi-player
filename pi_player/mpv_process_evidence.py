"""Linux cgroup v2 process inventory evidence, offline B3 primitive.

A future privileged launcher must create/dedicate an owned child cgroup and
ensure all MPV children enter it. This object cannot create or migrate cgroups,
kill processes, or clear owner slots by itself. Missing evidence fails closed.
"""
from __future__ import annotations

import os
import stat
from dataclasses import dataclass


class EvidenceError(RuntimeError):
    pass


@dataclass(frozen=True)
class GroupEvidence:
    empty: bool
    populated: int
    pids: tuple[int, ...]


def _read_at(dir_fd: int, name: str, limit: int = 65536) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        fd = os.open(name, flags, dir_fd=dir_fd)
    except OSError as exc:
        raise EvidenceError("Unable to inspect cgroup state") from exc
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise EvidenceError("Unexpected cgroup control file")
        data = os.read(fd, limit + 1)
        if len(data) > limit:
            raise EvidenceError("Oversized cgroup response")
        return data
    except OSError as exc:
        raise EvidenceError("Cannot read cgroup evidence") from exc
    finally:
        os.close(fd)


def inspect_cgroup(cgroup_directory: str) -> GroupEvidence:
    """Trusted static cgroup path only: validate BOTH events and procs.

    Caller must control directory creation and ownership, and must not use
    browser-provided paths. An empty report alone is insufficient if a child
    can still be launched: supervisor launch serialization is a separate gate.
    """
    if type(cgroup_directory) is not str or not os.path.isabs(cgroup_directory):
        raise EvidenceError("Absolute trusted cgroup path required")
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        directory = os.open(cgroup_directory, flags)
    except OSError as exc:
        raise EvidenceError("Cannot inspect cgroup directory") from exc
    try:
        events = _read_at(directory, "cgroup.events").decode("ascii")
        procs = _read_at(directory, "cgroup.procs").decode("ascii")
        values = {}
        for line in events.splitlines():
            parts = line.split()
            if len(parts) != 2 or parts[0] in values or not parts[1].isdigit():
                raise EvidenceError("Malformed cgroup events")
            values[parts[0]] = int(parts[1])
        if values.get("populated") not in (0, 1):
            raise EvidenceError("Missing or invalid populated flag")
        pids = []
        for line in procs.splitlines():
            if not line.isdecimal() or int(line) < 1:
                raise EvidenceError("Malformed cgroup process list")
            pids.append(int(line))
        if len(set(pids)) != len(pids):
            raise EvidenceError("Duplicate cgroup process identity")
        # A matching zero from both sources is necessary before releasing.
        return GroupEvidence(not pids and values["populated"] == 0,
                             values["populated"], tuple(pids))
    except UnicodeDecodeError as exc:
        raise EvidenceError("Invalid cgroup response") from exc
    finally:
        os.close(directory)

"""Optional Linux systemd-scope MPV launcher, never enabled by default.

A scope makes the *whole* MPV process tree visible to systemd cgroup v2.
Helper exit is NOT proof the renderer has gone away; every retirement must
also inspect the scope's populated state. No browser/HTTP input is accepted.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path

from .mpv_fd_transport import ReceivedVideo
from .mpv_process_evidence import GroupEvidence, inspect_cgroup


class ScopeError(RuntimeError):
    pass


@dataclass(frozen=True)
class ScopeHandle:
    unit: str
    request_id: str
    helper_pid: int


def _validated_media(media: ReceivedVideo) -> None:
    if not isinstance(media, ReceivedVideo) or media.fd < 3:
        raise ScopeError("Trusted media descriptor required")
    import stat
    info = os.fstat(media.fd)
    if (not stat.S_ISREG(info.st_mode) or info.st_ino != media.inode
            or info.st_dev != media.device or info.st_size <= 0):
        raise ScopeError("Media descriptor identity changed")


class ScopedMpvLauncher:
    """Single-session scope lifecycle controlled by a dedicated kiosk agent.

    The kiosk agent must keep its own process identity. Spawning or
    terminating is serialized; loss of evidence leaves the scope quarantined.
    """

    def __init__(self, *, mpv_binary: str = "/usr/bin/mpv",
                 systemd_run: str = "/usr/bin/systemd-run",
                 systemctl: str = "/usr/bin/systemctl"):
        if (not all(isinstance(v, str) and v.startswith("/") for v in
                    (mpv_binary, systemd_run, systemctl))):
            raise ScopeError("Trusted absolute executable paths required")
        self.mpv_binary, self.systemd_run, self.systemctl = (
            mpv_binary, systemd_run, systemctl)
        self._lock = threading.RLock()
        self._proc = None
        self._handle = None

    @staticmethod
    def scope_command(unit: str, fd: int, *, muted: bool, loop: bool,
                      systemd_run: str = "/usr/bin/systemd-run",
                      mpv_binary: str = "/usr/bin/mpv") -> list[str]:
        if not re.fullmatch(r"pi-player-mpv-[0-9a-f]{32}\.scope", unit):
            raise ScopeError("Untrusted scope name")
        if type(fd) is not int or fd < 3:
            raise ScopeError("Invalid inherited descriptor")
        if type(muted) is not bool or type(loop) is not bool:
            raise ScopeError("Invalid MPV options")
        return [
            systemd_run, "--user", "--scope", "--collect", f"--unit={unit}",
            "--", mpv_binary, "--no-config", "--no-terminal",
            "--profile=fast", "--vo=gpu", "--gpu-api=opengl",
            "--gpu-context=wayland", "--hwdec=no", "--keep-open=no",
            "--fullscreen=yes", f"--wayland-app-id={unit[:-6]}",
            "--mute=yes" if muted else "--mute=no",
            "--loop-file=inf" if loop else "--loop-file=no",
            "--", f"/proc/self/fd/{fd}",
        ]

    def launch(self, media: ReceivedVideo, *, muted: bool = True,
               loop: bool = False) -> ScopeHandle:
        with self._lock:
            if os.geteuid() == 0:
                raise ScopeError("Scope must launch as unprivileged kiosk account")
            if self._handle is not None:
                raise ScopeError("Previous renderer not yet reconciled")
            _validated_media(media)
            if not Path("/sys/fs/cgroup/cgroup.controllers").is_file():
                raise ScopeError("cgroup v2 unavailable")
            unit = f"pi-player-mpv-{uuid.uuid4().hex}.scope"
            argv = self.scope_command(unit, media.fd, muted=muted, loop=loop,
                                      systemd_run=self.systemd_run,
                                      mpv_binary=self.mpv_binary)
            try:
                proc = subprocess.Popen(
                    argv, pass_fds=(media.fd,), close_fds=True,
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL, start_new_session=True)
            except OSError as exc:
                raise ScopeError("Scope launch failed") from exc
            # Retain even when systemd-run exits early; its PID is not
            # necessarily the MPV child PID. Never launch again until retire.
            self._proc = proc
            self._handle = ScopeHandle(unit, str(uuid.uuid4()), proc.pid)
            return self._handle

    def scope_cgroup(self, handle: ScopeHandle) -> Path:
        with self._lock:
            if self._handle != handle:
                raise ScopeError("Stale scope handle")
            try:
                result = subprocess.run(
                    [self.systemctl, "--user", "show", handle.unit,
                     "--property=ControlGroup", "--value"],
                    capture_output=True, text=True, timeout=3, check=True)
            except (OSError, subprocess.CalledProcessError,
                    subprocess.TimeoutExpired) as exc:
                raise ScopeError("Scope inventory unavailable") from exc
            value = result.stdout.strip()
            # Do not permit traversal or system-level paths.
            if (not value.startswith("/user.slice/") or ".." in value
                    or not re.fullmatch(r"/[A-Za-z0-9_.@/-]+", value)):
                raise ScopeError("Unexpected systemd user scope cgroup")
            return Path("/sys/fs/cgroup") / value.lstrip("/")

    def evidence(self, handle: ScopeHandle) -> GroupEvidence:
        return inspect_cgroup(str(self.scope_cgroup(handle)))

    def stop(self, handle: ScopeHandle) -> None:
        """Request systemd to stop whole scope. Not proof of cleanup."""
        with self._lock:
            if self._handle != handle:
                raise ScopeError("Stale scope handle")
            try:
                subprocess.run([self.systemctl, "--user", "stop", handle.unit],
                               capture_output=True, timeout=5, check=True)
            except (OSError, subprocess.CalledProcessError,
                    subprocess.TimeoutExpired) as exc:
                raise ScopeError("Scope stop not confirmed") from exc

    def reconcile_empty(self, handle: ScopeHandle, *,
                        group_empty: bool, helper_exited: bool) -> None:
        """Only called after independent cgroup and helper inspection."""
        with self._lock:
            if self._handle != handle or group_empty is not True or helper_exited is not True:
                raise ScopeError("Cannot retire an occupied or unverified scope")
            if self._proc is None or self._proc.poll() is None:
                raise ScopeError("Scope helper has not exited")
            self._handle = self._proc = None

"""Experimental kiosk-owned MPV adapter; not connected to the HTTP API.

A controller process must run as the kiosk user. Neither process existence nor
exit code 0 is proof of media readiness or end-of-file.
"""
from __future__ import annotations

import json
import math
import os
import socket
import subprocess
import tempfile
import threading
import time
import uuid
from pathlib import Path

from .config import ASSET_DIR

VIDEO_SUFFIXES = frozenset({".mp4", ".webm"})


def validate_video_path(path: str | Path, asset_dir: Path = ASSET_DIR) -> Path:
    root = asset_dir.resolve(strict=True)
    candidate = Path(path).resolve(strict=True)
    if candidate.parent != root or not candidate.is_file() or candidate.suffix.lower() not in VIDEO_SUFFIXES:
        raise ValueError("Not a permitted local video asset")
    return candidate


def read_reply(ipc: Path, command: list, *, deadline_seconds: float = 1.0) -> dict:
    """Ignore unsolicited events and read complete JSON lines until request 1."""
    deadline = time.monotonic() + deadline_seconds
    data = bytearray()
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(max(0.001, deadline - time.monotonic()))
        client.connect(str(ipc))
        client.sendall((json.dumps({"command": command, "request_id": 1}) + "\n").encode())
        while time.monotonic() < deadline:
            client.settimeout(max(0.001, deadline - time.monotonic()))
            packet = client.recv(4096)
            if not packet:
                break
            data.extend(packet)
            if len(data) > 65536:
                raise OSError("MPV IPC reply exceeded 64 KiB")
            while b"\n" in data:
                line, _, remainder = data.partition(b"\n")
                data = bytearray(remainder)
                try:
                    parsed = json.loads(line)
                except (ValueError, UnicodeError) as exc:
                    raise OSError("Invalid MPV IPC JSON") from exc
                if not isinstance(parsed, dict):
                    raise OSError("Invalid MPV IPC response shape")
                if parsed.get("request_id") == 1:
                    return parsed
    raise OSError("No matching MPV IPC response before deadline")


class MpvPlayer:
    """At most one child per instance; the future kiosk agent must own one instance."""

    def __init__(self, *, asset_dir: Path = ASSET_DIR, mpv_binary: str = "/usr/bin/mpv"):
        self.asset_dir = Path(asset_dir)
        self.mpv_binary = mpv_binary
        self._lock = threading.RLock()
        self._process = None
        self._session = None
        self._ipc_dir = None
        self._ipc_path = None
        self._ever_progressed = False
        self._last_exit = None

    def _retire_exited(self):
        if self._process is not None and self._process.poll() is None:
            return False
        previous = self._process
        if previous is not None:
            self._last_exit = previous.poll()
        directory = self._ipc_dir
        self._process = self._session = self._ipc_dir = self._ipc_path = None
        self._ever_progressed = False
        if directory is not None:
            try:
                directory.cleanup()
            except OSError:
                pass  # A terminated child is never retained solely for temp cleanup.
        return True

    def start(self, path: str | Path, *, muted: bool = True, loop: bool = False) -> str:
        with self._lock:
            if os.geteuid() == 0:
                raise PermissionError("MPV must run as the unprivileged kiosk account")
            if not self._retire_exited():
                raise RuntimeError("An MPV session is already running")
            video = validate_video_path(path, self.asset_dir)
            runtime_value = os.environ.get("XDG_RUNTIME_DIR")
            if not runtime_value:
                raise RuntimeError("Kiosk XDG_RUNTIME_DIR is missing")
            runtime = Path(runtime_value)
            if not runtime.is_absolute() or not runtime.is_dir() or runtime.stat().st_uid != os.geteuid():
                raise RuntimeError("Kiosk XDG_RUNTIME_DIR is missing or owned by a different account")
            ipc_dir = tempfile.TemporaryDirectory(prefix="pi-player-mpv-", dir=runtime)
            ipc = Path(ipc_dir.name) / "control.sock"
            args = [
                self.mpv_binary, "--no-config", "--no-terminal",
                "--profile=fast", "--vo=gpu", "--gpu-api=opengl",
                "--gpu-context=wayland", "--hwdec=no", "--keep-open=no",
                f"--input-ipc-server={ipc}",
                "--mute=yes" if muted else "--mute=no",
                "--loop-file=inf" if loop else "--loop-file=no",
                "--", str(video),
            ]
            try:
                process = subprocess.Popen(
                    args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL, close_fds=True, start_new_session=True,
                )
            except Exception:
                ipc_dir.cleanup()
                raise
            self._process, self._ipc_dir, self._ipc_path = process, ipc_dir, ipc
            self._session = uuid.uuid4().hex
            self._ever_progressed = False
            self._last_exit = None
            return self._session

    def status(self, session: str) -> dict:
        with self._lock:
            if not session or session != self._session:
                raise ValueError("Stale or unknown MPV session")
            process = self._process
            ipc = self._ipc_path
            ever_progressed = self._ever_progressed
            code = process.poll()
            if code is not None:
                # A clean quit or window close also exits 0; this is NOT EOF evidence.
                return {"session": session, "state": "exited", "running": False,
                        "exit_code": code, "position_seconds": None, "eof": False}
        try:
            reply = read_reply(ipc, ["get_property", "time-pos"])
            if reply.get("error") != "success":
                raise OSError("MPV position not yet available")
            pos = reply.get("data")
            if isinstance(pos, bool) or not isinstance(pos, (int, float)) or not math.isfinite(pos):
                raise OSError("MPV position is invalid")
            position = float(pos)
            state = "playing" if position > 0 else "starting"
            error = None
        except (OSError, ValueError) as exc:
            position = None
            state = "monitor_error" if ever_progressed else "starting"
            error = str(exc)
        with self._lock:
            if session != self._session or self._process is not process:
                raise ValueError("MPV session replaced while reading status")
            if process.poll() is not None:
                return {"session": session, "state": "exited", "running": False,
                        "exit_code": process.poll(), "position_seconds": None, "eof": False}
            if position is not None and position > 0:
                self._ever_progressed = True
            result = {"session": session, "state": state, "running": True,
                      "exit_code": None, "position_seconds": position, "eof": False}
            if error is not None:
                result["monitor_error"] = error
            return result

    def stop(self, session: str, *, timeout: float = 3.0) -> bool:
        with self._lock:
            if not session or session != self._session:
                return False
            process = self._process
            if process.poll() is None:
                try:
                    process.terminate()
                    process.wait(timeout=timeout)
                except (subprocess.TimeoutExpired, OSError):
                    # Do not detach a live child or permit an overlapping start.
                    return False
            return self._retire_exited()

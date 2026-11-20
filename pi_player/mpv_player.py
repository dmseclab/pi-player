"""Opt-in MPV process adapter for the kiosk account.

This module is deliberately not connected to the HTTP API or playlist yet.
Only a trusted, kiosk-owned coordinator may call it. Never run it as root or
from the API service's different Unix account.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import tempfile
import threading
import uuid
from pathlib import Path

from .config import ASSET_DIR

VIDEO_SUFFIXES = frozenset({".mp4", ".webm"})


def validate_video_path(path: str | Path, asset_dir: Path = ASSET_DIR) -> Path:
    """Accept only existing local videos directly inside the configured asset dir."""
    root = asset_dir.resolve(strict=True)
    candidate = Path(path).resolve(strict=True)
    if candidate.parent != root or not candidate.is_file() or candidate.suffix.lower() not in VIDEO_SUFFIXES:
        raise ValueError("Not a permitted local video asset")
    return candidate


class MpvPlayer:
    """Own at most one MPV child process and its private JSON IPC socket.

    Caller is responsible for obtaining an asset path from a validated DB row.
    This class revalidates the path and refuses to replace a running session.
    """

    def __init__(self, *, asset_dir: Path = ASSET_DIR, mpv_binary: str = "/usr/bin/mpv"):
        self.asset_dir = Path(asset_dir)
        self.mpv_binary = mpv_binary
        self._lock = threading.RLock()
        self._process = None
        self._session = None
        self._ipc_dir = None
        self._ipc_path = None

    def _retire_exited(self):
        if self._process is not None and self._process.poll() is None:
            return False
        if self._ipc_dir is not None:
            self._ipc_dir.cleanup()
        self._process = self._session = self._ipc_dir = self._ipc_path = None
        return True

    def start(self, path: str | Path, *, muted: bool = True, loop: bool = False) -> str:
        with self._lock:
            if os.geteuid() == 0:
                raise PermissionError("MPV must run as the unprivileged kiosk account")
            if not self._retire_exited():
                raise RuntimeError("An MPV session is already running")
            video = validate_video_path(path, self.asset_dir)
            runtime = Path(os.environ.get("XDG_RUNTIME_DIR", ""))
            if not runtime.is_absolute() or not runtime.is_dir() or runtime.stat().st_uid != os.geteuid():
                raise RuntimeError("Kiosk XDG_RUNTIME_DIR is missing or not owned by this account")
            ipc_dir = tempfile.TemporaryDirectory(prefix="pi-player-mpv-", dir=runtime)
            ipc = Path(ipc_dir.name) / "control.sock"
            args = [
                self.mpv_binary,
                "--no-config", "--no-terminal", "--profile=fast",
                "--vo=gpu", "--gpu-api=opengl", "--gpu-context=wayland",
                "--hwdec=no", "--keep-open=no",
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
            self._process = process
            self._ipc_dir = ipc_dir
            self._ipc_path = ipc
            self._session = uuid.uuid4().hex
            return self._session

    def status(self, session: str) -> dict:
        with self._lock:
            if not session or session != self._session:
                raise ValueError("Stale or unknown MPV session")
            process = self._process
            code = process.poll()
            if code is not None:
                # Keep the session identity observable until the next start/stop.
                return {"session": session, "running": False, "exit_code": code,
                        "position_seconds": None, "eof": code == 0}
            try:
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                    client.settimeout(1.0)
                    client.connect(str(self._ipc_path))
                    client.sendall(b'{"command":["get_property","time-pos"],"request_id":1}\n')
                    data = b""
                    while b"\n" not in data and len(data) < 65536:
                        chunk = client.recv(4096)
                        if not chunk:
                            break
                        data += chunk
                responses = [json.loads(line) for line in data.splitlines() if line]
                result = next((r for r in responses if r.get("request_id") == 1), None)
                if result is None or result.get("error") != "success":
                    raise OSError("MPV playback position unavailable")
                position = result.get("data")
                if not isinstance(position, (float, int)) or isinstance(position, bool):
                    raise OSError("MPV playback position invalid")
                return {"session": session, "running": True, "exit_code": None,
                        "position_seconds": float(position), "eof": False}
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                return {"session": session, "running": True, "exit_code": None,
                        "position_seconds": None, "eof": False,
                        "monitor_error": str(exc)}

    def stop(self, session: str, *, timeout: float = 3.0) -> bool:
        """Return False on stale identity; leave an unkillable child tracked."""
        with self._lock:
            if not session or session != self._session:
                return False
            process = self._process
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    # Do not SIGKILL D-state tasks or start overlapping sessions.
                    return False
            self._retire_exited()
            return True

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
    def remaining():
        seconds = deadline - time.monotonic()
        if seconds <= 0:
            raise TimeoutError("MPV IPC deadline exceeded")
        return seconds

    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(remaining())
        client.connect(str(ipc))
        client.settimeout(remaining())
        client.sendall((json.dumps({"command": command, "request_id": 1}) + "\n").encode())
        while True:
            client.settimeout(remaining())
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
                if type(parsed.get("request_id")) is int and parsed["request_id"] == 1:
                    remaining()  # A late response cannot turn a timed-out read into success.
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
        self._last_position = None  # stable accumulation baseline
        self._last_valid_position = None  # most recent accepted sample
        self._last_progress_at = None
        self._poll_serial = 0
        self._applied_poll = 0

    def _retire_exited(self):
        if self._process is not None and self._process.poll() is None:
            return False
        previous = self._process
        if previous is not None:
            self._last_exit = previous.poll()
        directory = self._ipc_dir
        self._process = self._session = self._ipc_dir = self._ipc_path = None
        self._ever_progressed = False
        self._last_position = None
        self._last_valid_position = None
        self._last_progress_at = None
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
                try:
                    ipc_dir.cleanup()
                except OSError:
                    pass
                raise
            self._process, self._ipc_dir, self._ipc_path = process, ipc_dir, ipc
            self._session = uuid.uuid4().hex
            self._ever_progressed = False
            self._last_exit = None
            self._last_position = None
            self._last_valid_position = None
            self._last_progress_at = None
            self._poll_serial = self._applied_poll = 0
            return self._session

    def status(self, session: str) -> dict:
        """A positive time position alone does not prove playback is advancing.

        State becomes 'playing' only after a new position exceeds an earlier
        sample. Later flat samples become 'stalled' after 15 seconds. Actual
        rendered frames and natural EOF require the future kiosk supervisor.
        """
        with self._lock:
            if not session or session != self._session:
                raise ValueError("Stale or unknown MPV session")
            process = self._process
            ipc = self._ipc_path
            self._poll_serial += 1
            serial = self._poll_serial
            if process.poll() is not None:
                code = process.poll()
                self._retire_exited()
                return {"session": session, "state": "exited", "running": False,
                        "exit_code": code, "position_seconds": None, "eof": False}
        position = None
        error = None
        try:
            reply = read_reply(ipc, ["get_property", "time-pos"])
            if reply.get("error") != "success":
                raise OSError("MPV position not yet available")
            raw_position = reply.get("data")
            if isinstance(raw_position, bool) or not isinstance(raw_position, (float, int)):
                raise OSError("MPV position is invalid")
            try:
                checked_position = float(raw_position)
            except (OverflowError, ValueError) as exc:
                raise OSError("MPV position is invalid") from exc
            if not math.isfinite(checked_position) or checked_position < 0:
                raise OSError("MPV position is invalid")
            position = checked_position  # Only validated samples can enter tracking.
        except (OSError, ValueError, TimeoutError) as exc:
            error = str(exc)
        with self._lock:
            if session != self._session or self._process is not process:
                raise ValueError("MPV session replaced while reading status")
            if process.poll() is not None:
                code = process.poll()
                self._retire_exited()
                return {"session": session, "state": "exited", "running": False,
                        "exit_code": code, "position_seconds": None, "eof": False}
            if serial < self._applied_poll:
                raise ValueError("Out-of-order MPV status response")
            self._applied_poll = serial
            now = time.monotonic()
            # Detect even tiny rewinds against the latest *valid* sample,
            # independently of the cumulative 50 ms progress baseline.
            rewind = (position is not None and self._last_valid_position is not None
                      and position < self._last_valid_position)
            if rewind:
                self._last_position = position
            delta = (position - self._last_position
                     if position is not None and self._last_position is not None else None)
            # A nominal 50 ms advance (e.g. 2.00 -> 2.05) must not be
            # lost to binary float representation; tolerance is 1 ns.
            advanced = (delta is not None and not rewind
                        and (delta >= 0.05 or math.isclose(
                            delta, 0.05, rel_tol=0.0, abs_tol=1e-9)))
            if advanced:
                self._last_progress_at = now
                self._ever_progressed = True
                self._last_position = position
            elif position is not None and self._last_position is None:
                self._last_position = position
            if position is not None:
                self._last_valid_position = position
            since_progress = (now - self._last_progress_at
                              if self._last_progress_at is not None else None)
            if since_progress is not None and since_progress >= 15.0:
                state = "stalled"
            elif since_progress is not None:
                state = "playing"
            elif error is not None:
                state = "starting"
            else:
                state = "starting"
            result = {"session": session, "state": state, "running": True,
                      "exit_code": None, "position_seconds": position, "eof": False,
                      "progress_age_seconds": round(since_progress, 3) if since_progress is not None else None}
            if error is not None:
                result["monitor_error"] = error
            return result

    def stop(self, session: str, *, timeout: float = 3.0) -> bool:
        if (isinstance(timeout, bool) or not isinstance(timeout, (float, int))
                or not 0 < timeout <= 10):
            raise ValueError("Stop timeout must be between 0 and 10 seconds")
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

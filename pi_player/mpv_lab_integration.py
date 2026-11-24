"""Opt-in, same-account laboratory MP4 renderer. No production activation.

One WebSocket owns one playback, and closing it retires the renderer. The
existing API service owns the child, so systemd also cleans its service cgroup
on API restart. This is not a separate-UID security boundary or proof of
physical presentation; the operator must verify those lab acceptance gates.
"""
from __future__ import annotations

import asyncio
import hmac
import json
import logging
import math
import os
import re
import socket
import stat
import subprocess
import tempfile
import time
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import WebSocket, WebSocketDisconnect

from .config import ASSET_DIR
from .db import db, get_setting
from .main import app
from .mpv_broker import BrokerError, OpenedMedia
from .mpv_catalog import lookup_video, check_opened_media
from .mpv_player import read_reply, renderer_arguments

LOG = logging.getLogger('uvicorn.error')
LAUNCH_STAGES = frozenset({'inventory', 'wayland', 'catalog', 'asset-open',
                           'asset-checksum', 'catalog-recheck', 'ipc-directory',
                           'spawn', 'supervision'})


def failure_reason(stage, exc):
    stage = stage if isinstance(stage, str) and stage in LAUNCH_STAGES else 'control'
    kind = type(exc).__name__
    if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,63}', kind):
        kind = 'Error'
    errno = getattr(exc, 'errno', None)
    return f'{stage}:{kind}' + (f':errno={errno}' if type(errno) is int else '')
TOKEN_PATH = Path("/etc/pi-player/mpv-lab-token")
ORIGIN = "http://127.0.0.1:8000"
MAX_LAB_BYTES = 64 * 1024 * 1024
LEASE_SECONDS = 12
_lock = asyncio.Lock()
_renderer = None


def lab_token():
    """Root-owned explicit opt-in; no token means no renderer access."""
    try:
        if socket.gethostname().split(".")[0] != "pi-player" or os.geteuid() == 0:
            return None
        fd = os.open(TOKEN_PATH, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            info = os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0
                    or info.st_mode & 0o037 or info.st_size > 65):
                return None
            value = os.read(fd, 66).decode("ascii").strip()
            return value if re.fullmatch("[a-f0-9]{64}", value) else None
        finally:
            os.close(fd)
    except (OSError, UnicodeError, AttributeError):
        return None


def authorized(ws, supplied):
    expected = lab_token()
    return (expected is not None and type(supplied) is str
            and len(supplied) == 64 and ws.client is not None
            and ws.client.host == "127.0.0.1"
            and ws.headers.get("origin") == ORIGIN
            and ws.headers.get("host") == "127.0.0.1:8000"
            and hmac.compare_digest(expected, supplied))


def eligible(item_id):
    with db() as conn:
        if get_setting(conn, "setup_required", "0") == "1":
            raise ValueError("Setup incomplete")
        grant = lookup_video(conn, item_id, asset_root=str(ASSET_DIR),
                             now=datetime.now().astimezone())
    if (not grant.muted or grant.loop or grant.display_mode != "fit"
            or not grant.record.filename.endswith(".mp4")
            or grant.size_bytes > MAX_LAB_BYTES):
        raise ValueError("Outside initial laboratory video profile")
    return grant


def graphical_env():
    uid = os.geteuid()
    runtime = Path("/run/user") / str(uid)
    display = runtime / "wayland-0"
    if (runtime.stat().st_uid != uid or runtime.stat().st_mode & 0o077
            or not stat.S_ISSOCK(display.stat().st_mode)
            or display.stat().st_uid != uid):
        raise OSError("Trusted Wayland session unavailable")
    return {**os.environ, "XDG_RUNTIME_DIR": str(runtime),
            "WAYLAND_DISPLAY": "wayland-0",
            "DBUS_SESSION_BUS_ADDRESS": "unix:path=" + str(runtime / "bus")}


def any_mpv():
    """Conservative appliance UID inventory, including manual test processes."""
    result = subprocess.run(["/usr/bin/pgrep", "-u", str(os.geteuid()), "-x", "mpv"],
                            capture_output=True, timeout=2)
    if result.returncode not in (0, 1):
        raise OSError("MPV inventory unavailable")
    return result.returncode == 0


class LabRenderer:
    def __init__(self, item_id):
        self.item_id = item_id
        self.grant = None
        self.proc = None
        self.directory = None
        self.ipc = None
        self.app_id = "pi-player-mpv-" + uuid.uuid4().hex
        self.env = None
        self.started = time.monotonic()
        self.last_pos = None
        self.last_progress = None
        self.progressed = False
        self.stage = 'inventory'

    def launch(self):
        if any_mpv():
            raise RuntimeError("Another MPV process exists")
        self.stage = 'wayland'
        self.env = graphical_env()
        self.stage = 'catalog'
        grant = eligible(self.item_id)
        self.stage = 'asset-open'
        root = os.open(ASSET_DIR, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            fd = os.open(grant.record.filename,
                         os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                         dir_fd=root)
        finally:
            os.close(root)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode):
                raise ValueError("Not a regular asset")
            media = OpenedMedia(fd, self.item_id, grant.revision, "", info.st_ino, info.st_dev)
            self.stage = 'asset-checksum'
            check_opened_media(media, grant)
            self.stage = 'catalog-recheck'
            if eligible(self.item_id) != grant:
                raise ValueError("Catalog changed")
            self.stage = 'ipc-directory'
            self.directory = tempfile.TemporaryDirectory(prefix="pi-player-mpv-",
                                                          dir=self.env["XDG_RUNTIME_DIR"])
            self.ipc = Path(self.directory.name) / "control.sock"
            args = ["/usr/bin/mpv", *renderer_arguments(muted=True, loop=False),
                    "--keep-open=yes", "--keep-open-pause=yes", "--load-scripts=no",
                    "--ytdl=no", "--osc=no", "--input-default-bindings=no",
                    "--input-vo-keyboard=no", "--demuxer-lavf-format=mov",
                    "--demuxer-lavf-o=protocol_whitelist=file",
                    "--wayland-app-id=" + self.app_id,
                    "--input-ipc-server=" + str(self.ipc), "--",
                    "/proc/self/fd/" + str(fd)]
            self.stage = 'spawn'
            self.proc = subprocess.Popen(args, env=self.env, pass_fds=(fd,),
                                         close_fds=True, start_new_session=True,
                                         stdin=subprocess.DEVNULL,
                                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.grant = grant
            self.started = time.monotonic()
            self.stage = 'supervision'
        finally:
            os.close(fd)

    def property(self, name):
        try:
            reply = read_reply(self.ipc, ["get_property", name], deadline_seconds=0.5)
            return reply.get("data") if reply.get("error") == "success" else None
        except (OSError, ValueError, TimeoutError):
            return None

    def inspect(self):
        if self.proc is None or self.proc.poll() is not None:
            LOG.warning("Lab MPV child exited before completion: code=%s",
                        None if self.proc is None else self.proc.returncode)
            return "fallback"
        try:
            if eligible(self.item_id) != self.grant:
                return "cancelled"
        except (BrokerError, ValueError):
            return "cancelled"
        now = time.monotonic()
        pos = self.property("time-pos")
        if type(pos) in (float, int) and math.isfinite(pos) and pos >= 0:
            if self.last_pos is not None and pos >= self.last_pos + 0.05:
                self.last_progress = now
            if self.last_pos is None or pos >= self.last_pos + 0.05:
                self.last_pos = pos
        if self.last_progress is not None and not self.progressed:
            windows = subprocess.run(["/usr/bin/wlrctl", "toplevel", "list"],
                                     env=self.env, capture_output=True, text=True,
                                     timeout=2, check=True)
            self.progressed = any(line.startswith(self.app_id + ":")
                                  for line in windows.stdout.splitlines())
        if self.property("eof-reached") is True:
            return "completed" if self.progressed else "fallback"
        if not self.progressed:
            return "fallback" if now - self.started >= 30 else "starting"
        if now - self.last_progress >= 15:
            return "fallback"
        return "playing"

    def retire(self):
        """Reap exact child, require empty group and no remaining UID MPV."""
        try:
            if self.proc is not None:
                if self.proc.poll() is None:
                    self.proc.terminate()
                    try:
                        self.proc.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        self.proc.kill()
                        self.proc.wait(timeout=3)
                try:
                    os.killpg(self.proc.pid, 0)
                    return False
                except ProcessLookupError:
                    pass
            if any_mpv():
                return False
            if self.directory is not None:
                self.directory.cleanup()
                self.directory = None
            return True
        except (OSError, subprocess.SubprocessError):
            return False


async def retire():
    global _renderer
    try:
        if _renderer is None:
            return not await asyncio.to_thread(any_mpv)
        clean = await asyncio.to_thread(_renderer.retire)
        if clean:
            _renderer = None
        return clean
    except Exception as exc:
        LOG.warning("Lab MPV cleanup unverified: %s", type(exc).__name__)
        return False


async def read_message(ws, timeout):
    raw = await asyncio.wait_for(ws.receive_text(), timeout)
    if len(raw) > 1024:
        raise ValueError("Oversized lab message")
    body = json.loads(raw)
    if type(body) is not dict:
        raise ValueError("Invalid lab message")
    return body


@app.websocket("/api/player/mpv-lab")
async def mpv_lab(ws: WebSocket):
    global _renderer
    if (lab_token() is None or ws.client is None or ws.client.host != "127.0.0.1"
            or ws.headers.get("origin") != ORIGIN):
        await ws.close(code=1008)
        return
    await ws.accept()
    try:
        first = await read_message(ws, 3)
        action_label = first.get("action")
        action_label = action_label if action_label in ("start", "check") else "invalid"
        if not authorized(ws, first.get("token")):
            LOG.warning("Lab MPV request rejected: action=%s host_match=%s token_match=%s",
                        action_label, ws.headers.get("host") == "127.0.0.1:8000",
                        isinstance(first.get("token"), str) and hmac.compare_digest(
                            (lab_token() or "").encode(), first["token"].encode()))
            await ws.close(code=1008)
            return
        action = first.get("action")
        if action not in ("start", "check"):
            raise ValueError("Unknown action")
        if set(first) != ({"action", "token", "item_id"} if action == "start"
                          else {"action", "token"}):
            raise ValueError("Invalid fields")
        if action == "start":
            item = first.get("item_id")
            LOG.info("Lab MPV start request: item=%s", item if isinstance(item, str) and re.fullmatch(r"[0-9a-f-]{36}", item) else "invalid")
        if _lock.locked():
            LOG.warning("Lab MPV request busy: action=%s", action)
            await ws.send_json({"state": "busy", "clean": False})
            return
        terminal = None
        async with _lock:
            try:
                if not await retire():
                    terminal = {"state": "quarantined", "clean": False}
                elif action == "check":
                    terminal = {"state": "clean", "clean": True}
                else:
                    if type(first["item_id"]) is not str or len(first["item_id"]) != 36:
                        raise ValueError("Invalid item")
                    _renderer = LabRenderer(first["item_id"])
                    await asyncio.to_thread(_renderer.launch)
                    LOG.info("Lab MPV renderer launched")
                    await ws.send_json({"state": "starting"})
                    lease = time.monotonic() + LEASE_SECONDS
                    last_state = "starting"
                    while True:
                        try:
                            msg = await read_message(ws, 1)
                            if msg == {"action": "stop"}:
                                state = "cancelled"
                                break
                            if msg != {"action": "ping"}:
                                raise ValueError("Invalid playback message")
                            lease = time.monotonic() + LEASE_SECONDS
                        except asyncio.TimeoutError:
                            pass
                        if time.monotonic() >= lease or not authorized(ws, first["token"]):
                            state = "fallback"
                            break
                        state = await asyncio.to_thread(_renderer.inspect)
                        if state not in ("starting", "playing"):
                            break
                        if state != last_state or state == "playing":
                            await ws.send_json({"state": state})
                        last_state = state
                    clean = await retire()
                    terminal = {"state": state if clean else "quarantined", "clean": clean}
            except WebSocketDisconnect:
                LOG.info("Lab MPV client disconnected: action=%s", action)
            except Exception as exc:
                reason = failure_reason(getattr(_renderer, "stage", None), exc)
                LOG.warning("Lab MPV failed: %s", reason)
                clean = await retire()
                terminal = {"state": "fallback" if clean else "quarantined",
                            "clean": clean, "reason": reason}
            finally:
                # On disconnect or cancellation, retire while still owning the lock.
                # A completed check/retirement needs no second inventory pass.
                if terminal is None:
                    await retire()
        # The client may immediately start its next request on receiving a
        # terminal response. Release ownership before acknowledging cleanup.
        if terminal is not None:
            await ws.send_json(terminal)
    except (WebSocketDisconnect, asyncio.TimeoutError, ValueError, RuntimeError) as exc:
        LOG.warning("Lab MPV request ended before completion: %s", type(exc).__name__)
    finally:
        try:
            await ws.close()
        except (RuntimeError, WebSocketDisconnect):
            pass

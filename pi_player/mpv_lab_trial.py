"""Manually gated Linux lab-only MPV trial: disabled unless explicitly opted in.

An experiment for the display owner, NOT integrated into the normal player
loop. The trial never changes systemd unit files, accounts, playlist state,
Chromium profile or remote devices. An operator must be physically available.
"""
from __future__ import annotations

import argparse
import json
import os
import pwd
import socket
import time
import uuid
from pathlib import Path

from .mpv_fd_transport import recv_video_fd
from .mpv_scope_launcher import ScopedMpvLauncher, ScopeError


def _uid(name: str) -> int:
    return pwd.getpwnam(name).pw_uid


def preflight(*, hostname: str, is_root: bool, hybrid_ack: bool,
              wayland_display: str | None, runtime: str | None,
              broker_socket: Path) -> tuple[str, ...]:
    problems = []
    if hostname != "pi-player":
        problems.append("lab-hostname")
    if is_root:
        problems.append("root-user")
    if not hybrid_ack:
        problems.append("no-manual-lab-approval")
    if not wayland_display:
        problems.append("wayland-session-missing")
    if not runtime or not Path(runtime).is_absolute():
        problems.append("runtime-dir-missing")
    if not broker_socket.is_absolute() or not broker_socket.is_socket():
        problems.append("broker-socket-unavailable")
    return tuple(problems)


def run_trial(*, item_id: str, broker_socket: Path, broker_user: str,
              seconds: int) -> dict:
    if not 1 <= seconds <= 120:
        raise ValueError("Lab trial must be between 1 and 120 seconds")
    if str(uuid.UUID(item_id)) != item_id:
        raise ValueError("Canonical catalog item UUID required")
    launcher = ScopedMpvLauncher()
    with socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET) as client:
        client.settimeout(3)
        client.connect(str(broker_socket))
        client.send(json.dumps({"version": 1, "action": "video",
                                "item_id": item_id}).encode("ascii"))
        with recv_video_fd(client, broker_uid=_uid(broker_user)) as media:
            handle = launcher.launch(media, muted=True, loop=False)
    # This CLI deliberately does not call wlrctl or claim a presented frame.
    # It exercises MPV process/FD startup and expects manual observation.
    try:
        time.sleep(seconds)
    finally:
        launcher.stop(handle)
    # A successful systemd stop is not an empty cgroup confirmation.
    # Leave a trace for the operator to verify systemd group cleanup.
    return {"scope": handle.unit, "stop_requested": True,
            "retirement_verified": False, "first_frame_verified": False}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--item-id")
    p.add_argument("--broker-socket", type=Path,
                   default=Path("/run/pi-player-mpv-broker/media.sock"))
    p.add_argument("--broker-user", default="pi-player-broker")
    p.add_argument("--duration-seconds", type=int, default=20)
    p.add_argument("--live-lab", action="store_true",
                   help="Manual experimental MPV start, not player deployment")
    args = p.parse_args(argv)
    problems = preflight(
        hostname=socket.gethostname(), is_root=os.geteuid() == 0,
        hybrid_ack=args.live_lab,
        wayland_display=os.environ.get("WAYLAND_DISPLAY"),
        runtime=os.environ.get("XDG_RUNTIME_DIR"),
        broker_socket=args.broker_socket)
    if not args.live_lab:
        print(json.dumps({"mode": "preflight", "problems": problems,
                          "launch_attempted": False}, indent=2))
        return 0
    if problems:
        print(json.dumps({"mode": "blocked", "problems": problems}, indent=2))
        return 2
    if not args.item_id:
        p.error("--item-id is required for --live-lab")
    print(json.dumps(run_trial(item_id=args.item_id,
                               broker_socket=args.broker_socket,
                               broker_user=args.broker_user,
                               seconds=args.duration_seconds), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

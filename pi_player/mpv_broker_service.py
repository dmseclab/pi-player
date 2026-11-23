"""Opt-in local MPV media broker. Never enabled by default or exposed over HTTP.

SOCK_SEQPACKET, Unix kernel peer credentials and a read-only catalog. This
daemon supplies media FDs ONLY; it never starts or controls MPV. A single
connection is processed at a time with bounded timeouts.
"""
from __future__ import annotations

import argparse
import os
import pwd
import socket
import sqlite3
import stat
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .mpv_broker import BrokerError, OfflineMediaBroker
from .mpv_handoff import OfflineHandoffCoordinator
from .mpv_owner import OfflineOwner


def identity(name: str) -> int:
    if not name or name in ("root", "nobody"):
        raise RuntimeError("Dedicated service account required")
    return pwd.getpwnam(name).pw_uid


def validate_runtime_directory(directory: Path) -> None:
    if not directory.is_absolute() or directory.is_symlink():
        raise RuntimeError("Absolute non-symlink socket directory required")
    info = directory.stat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid()
            or (info.st_mode & 0o077) != 0):
        raise RuntimeError("Broker runtime directory must be owned and private")


def run(*, directory: Path, database: Path, asset_root: Path,
        api_user: str, kiosk_user: str) -> None:
    api_uid, kiosk_uid = identity(api_user), identity(kiosk_user)
    broker_uid = os.geteuid()
    if (broker_uid == 0 or len({api_uid, kiosk_uid, broker_uid}) != 3
            or not database.is_absolute() or not asset_root.is_absolute()):
        raise RuntimeError("Broker must use a third unprivileged account")
    validate_runtime_directory(directory)
    path = directory / "media.sock"
    if path.exists() or path.is_symlink():
        raise RuntimeError("Refusing to replace an existing broker socket")
    def readonly_db():
        # Read-only SQLite URI prevents write transactions by the broker.
        return sqlite3.connect(database.as_uri() + "?mode=ro",
                               uri=True, timeout=2)
    owner = OfflineOwner()
    owner.reconcile_empty()  # This owner is for FD grants only, never process slots.
    with OfflineMediaBroker(str(asset_root),
                            kiosk_uid=kiosk_uid, api_uid=api_uid) as broker:
        coordinator = OfflineHandoffCoordinator(
            broker=broker, owner=owner,
            connection_factory=readonly_db, asset_root=str(asset_root))
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        try:
            listener.bind(str(path))
            os.chmod(path, 0o660)
            # The runtime directory and socket group must be provisioned
            # separately by the opt-in installer, never by this daemon.
            listener.listen(4)
            listener.settimeout(1.0)
            while True:
                try:
                    peer, _ = listener.accept()
                except socket.timeout:
                    continue
                with peer:
                    peer.settimeout(3.0)
                    try:
                        coordinator.serve_one(peer, now=datetime.now(ZoneInfo("Africa/Johannesburg")))
                    except (BrokerError, OSError, ValueError, sqlite3.Error):
                        # Do not send detailed authorization errors to peer.
                        pass
        finally:
            listener.close()
            # Unlink only the socket object we created.
            if path.is_socket():
                path.unlink()


def main(argv=None):
    p = argparse.ArgumentParser(description="Opt-in local media FD broker")
    p.add_argument("--runtime-dir", type=Path, required=True)
    p.add_argument("--database", type=Path, required=True)
    p.add_argument("--assets", type=Path, required=True)
    p.add_argument("--api-user", default="pi")
    p.add_argument("--kiosk-user", default="pi-player-mpv")
    args = p.parse_args(argv)
    run(directory=args.runtime_dir, database=args.database,
        asset_root=args.assets, api_user=args.api_user, kiosk_user=args.kiosk_user)


if __name__ == "__main__":
    main()

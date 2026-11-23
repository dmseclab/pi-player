"""Offline Phase 2B-2 coordinator: trusted owner + fresh catalog + FD handoff.

Never connected to HTTP or to a running kiosk. A production service MUST own
every owner transition under this coordinator and securely manage the Unix
socket, database permission policy and immutable media publication.
"""
from __future__ import annotations

import sqlite3
import threading
from datetime import datetime
from typing import Callable

from .mpv_broker import BrokerError, OfflineMediaBroker, peer_credentials
from .mpv_catalog import lookup_video, check_opened_media
from .mpv_fd_transport import send_video_fd
from .mpv_owner import OfflineOwner, OwnerLease, OwnerError


class OfflineHandoffCoordinator:
    def __init__(self, *, broker: OfflineMediaBroker, owner: OfflineOwner,
                 connection_factory: Callable[[], sqlite3.Connection],
                 asset_root: str):
        self.broker = broker
        self.owner = owner
        self.connection_factory = connection_factory
        self.asset_root = asset_root
        self._lock = threading.RLock()
        self._bindings = {}

    def bind_kiosk(self, conn, owner_id: str) -> OwnerLease:
        """Trusted local registration; no browser owner IDs from user traffic."""
        with self._lock:
            peer = peer_credentials(conn)
            if peer.uid != self.broker.kiosk_uid:
                raise BrokerError("Untrusted kiosk peer")
            lease = self.owner.replace_owner(owner_id)
            self._bindings.clear()
            self._bindings[id(conn)] = (conn, peer, lease)
            return lease

    def disconnect(self, conn) -> None:
        """Revoke only the lease belonging to this specific connection."""
        with self._lock:
            bound = self._bindings.pop(id(conn), None)
            if bound is not None and bound[0] is conn:
                try:
                    self.owner.revoke_owner(bound[2])
                except OwnerError:
                    pass

    def _check_binding(self, conn, lease: OwnerLease) -> None:
        bound = self._bindings.get(id(conn))
        if bound is None or bound[0] is not conn or bound[2] != lease:
            raise BrokerError("No live kiosk binding for owner")
        peer = peer_credentials(conn)
        if peer != bound[1]:
            raise BrokerError("Kiosk peer identity changed")
        self.owner.require_current(lease)

    def _lookup_fresh(self, item_id: str, now: datetime):
        # A new read connection each time prevents accidental reuse of a
        # caller-pinned WAL snapshot. Production factory must be readonly.
        conn = self.connection_factory()
        try:
            if not isinstance(conn, sqlite3.Connection):
                raise BrokerError("Trusted SQLite factory required")
            conn.execute("PRAGMA query_only=ON")
            return lookup_video(conn, item_id,
                                asset_root=self.asset_root, now=now)
        finally:
            conn.close()

    def handoff(self, conn, lease: OwnerLease, item_id: str, *,
                now: datetime) -> None:
        """Perform serialized validation and descriptor send, no MPV spawn.

        Freshness checks are intentionally after the file hash, just before
        sendmsg. File publication must still prevent in-place modifications.
        """
        with self._lock:
            self._check_binding(conn, lease)
            first = self._lookup_fresh(item_id, now)
            with self.broker.open_video(conn, lease, first.record) as opened:
                check_opened_media(opened, first)
                updated = self._lookup_fresh(item_id, now)
                if updated != first:
                    raise BrokerError("Catalog changed during media verification")
                self._check_binding(conn, lease)
                send_video_fd(conn, opened, kiosk_uid=self.broker.kiosk_uid)

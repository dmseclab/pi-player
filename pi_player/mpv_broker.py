"""Phase 2B-2 isolated Unix media broker primitives (NOT deployed).

No server, listening socket, endpoint, service, browser bridge, or installation.
Only an already-connected AF_UNIX peer with kernel-reported credentials may
request a descriptor for a *trusted* broker-selected media record. The caller
cannot supply paths or a claimed UID. Linux only.
"""
from __future__ import annotations

import os
import socket
import stat
import struct
import threading
import uuid
from dataclasses import dataclass, field

from pi_player.mpv_owner import OwnerLease

_EXTENSIONS = {".mp4", ".webm"}
_MAX_FILENAME = 180


class BrokerError(ValueError):
    """Reject unavailable platform, unauthorized peer, or unsafe media."""


@dataclass(frozen=True)
class Peer:
    pid: int
    uid: int
    gid: int


@dataclass(frozen=True)
class MediaRecord:
    """Trusted catalog result, not caller-provided JSON or a path argument."""
    item_id: str
    filename: str
    playlist_revision: str
    enabled: bool
    video: bool


@dataclass
class OpenedMedia:
    """Caller owns this FD. It stays pinned to the opened inode until closed."""
    fd: int = field(repr=False)
    item_id: str
    playlist_revision: str
    owner_epoch: str = field(repr=False)
    inode: int
    device: int

    def close(self) -> None:
        if self.fd >= 0:
            fd, self.fd = self.fd, -1
            os.close(fd)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def peer_credentials(conn: socket.socket) -> Peer:
    """Read Linux SO_PEERCRED from an established AF_UNIX connection."""
    if not isinstance(conn, socket.socket) or conn.family != socket.AF_UNIX:
        raise BrokerError("A connected Unix socket is required")
    option = getattr(socket, "SO_PEERCRED", None)
    if option is None:
        raise BrokerError("Linux SO_PEERCRED is required")
    try:
        raw = conn.getsockopt(socket.SOL_SOCKET, option, struct.calcsize("3i"))
        if len(raw) != struct.calcsize("3i"):
            raise BrokerError("Incomplete kernel peer credentials")
        pid, uid, gid = struct.unpack("3i", raw)
    except OSError as exc:
        raise BrokerError("Unable to verify Unix peer") from exc
    if pid <= 0 or uid < 0 or gid < 0:
        raise BrokerError("Invalid kernel peer credentials")
    return Peer(pid, uid, gid)


def _uuid(value: str) -> None:
    if type(value) is not str:
        raise BrokerError("Invalid media item ID")
    try:
        if str(uuid.UUID(value)) != value:
            raise BrokerError("Noncanonical media item ID")
    except ValueError as exc:
        raise BrokerError("Invalid media item ID") from exc


def _filename(value: str) -> None:
    # One regular file in a broker-owned root. Never descend directories.
    if (type(value) is not str or not 1 <= len(value) <= _MAX_FILENAME
            or value in (".", "..") or "/" in value or "\\" in value
            or "\x00" in value or value.startswith(".")
            or not value.isascii() or
            not all(ch.isalnum() or ch in "._-" for ch in value)
            or os.path.splitext(value)[1].lower() not in _EXTENSIONS):
        raise BrokerError("Invalid catalog media filename")


class OfflineMediaBroker:
    """Broker-only helper; no automatic trust in data class constructors.

    The future owner must call this with a trusted current lease and a catalog
    record checked for playlist/schedule entitlement. Credentials are derived
    from the connected kernel socket, not from JSON metadata. This class does
    not itself verify lease freshness or schedule eligibility.
    """

    def __init__(self, root: str, *, kiosk_uid: int, api_uid: int):
        if (type(kiosk_uid) is not int or type(api_uid) is not int
                or kiosk_uid < 0 or api_uid < 0 or kiosk_uid == api_uid):
            raise BrokerError("API and kiosk require distinct nonnegative UIDs")
        if type(root) is not str or not os.path.isabs(root):
            raise BrokerError("Media root must be an absolute trusted directory")
        self.kiosk_uid = kiosk_uid
        self.api_uid = api_uid
        self._fd_lock = threading.Lock()
        self._root_fd = -1
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
        root_fd = -1
        try:
            root_fd = os.open(root, flags)
            if not stat.S_ISDIR(os.fstat(root_fd).st_mode):
                raise BrokerError("Media root is not a directory")
            self._root_fd = root_fd
            root_fd = -1
        except OSError as exc:
            raise BrokerError("Cannot open trusted media root") from exc
        finally:
            if root_fd >= 0:
                os.close(root_fd)

    def close(self) -> None:
        # The same lock protects the dirfd through openat acquisition.
        # A returned leaf fd remains independent after close().
        with self._fd_lock:
            if self._root_fd >= 0:
                fd, self._root_fd = self._root_fd, -1
                os.close(fd)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def open_video(self, conn: socket.socket, lease: OwnerLease,
                   record: MediaRecord) -> OpenedMedia:
        peer = peer_credentials(conn)
        if peer.uid != self.kiosk_uid:
            raise BrokerError("Peer is not the kiosk service account")
        # Owner lease and catalog record are trusted broker-internal inputs,
        # NOT sufficient evidence of authenticated browser-owner identity.
        if (not isinstance(lease, OwnerLease) or
                type(lease.epoch) is not str or
                len(lease.epoch) != 64 or
                any(ch not in "0123456789abcdef" for ch in lease.epoch)):
            raise BrokerError("Invalid owner lease")
        if not isinstance(record, MediaRecord):
            raise BrokerError("Missing trusted catalog media record")
        _uuid(record.item_id)
        _filename(record.filename)
        if (type(record.playlist_revision) is not str
                or not 1 <= len(record.playlist_revision) <= 128
                or not all(ch.isalnum() or ch in "-_." for ch in record.playlist_revision)
                or type(record.enabled) is not bool or not record.enabled
                or type(record.video) is not bool or not record.video):
            raise BrokerError("Catalog record not eligible for video")
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        try:
            with self._fd_lock:
                if self._root_fd < 0:
                    raise BrokerError("Media broker has been closed")
                fd = os.open(record.filename, flags, dir_fd=self._root_fd)
        except OSError as exc:
            raise BrokerError("Media file could not be opened safely") from exc
        try:
            identity = os.fstat(fd)
            if not stat.S_ISREG(identity.st_mode):
                raise BrokerError("Media object is not a regular file")
            if identity.st_size <= 0:
                raise BrokerError("Empty media file")
            return OpenedMedia(fd, record.item_id, record.playlist_revision,
                               lease.epoch, identity.st_ino, identity.st_dev)
        except BaseException:
            os.close(fd)
            raise

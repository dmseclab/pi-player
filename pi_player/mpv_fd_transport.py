"""Feature-disabled Linux descriptor handoff over authenticated Unix sockets.

The future trusted coordinator owns owner-freshness/catalog rechecks. This
module only transfers an already-validated, opened descriptor. No listener,
API route, MPV spawn or installed service is created.
"""
from __future__ import annotations

import array
import json
import os
import socket
import stat
import uuid
from dataclasses import dataclass

from .mpv_broker import BrokerError, OpenedMedia, peer_credentials

MAX_MESSAGE = 1024


@dataclass(frozen=True)
class ReceivedVideo:
    fd: int
    item_id: str
    revision: str
    inode: int
    device: int

    def close(self):
        if self.fd >= 0:
            os.close(self.fd)
            object.__setattr__(self, "fd", -1)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def _packet_socket(conn):
    if (not isinstance(conn, socket.socket) or conn.family != socket.AF_UNIX
            or (conn.type & socket.SOCK_SEQPACKET) != socket.SOCK_SEQPACKET):
        raise BrokerError("Linux Unix seqpacket connection required")


def _canonical_uuid(value):
    if type(value) is not str:
        return False
    try:
        return str(uuid.UUID(value)) == value
    except ValueError:
        return False


def send_video_fd(conn: socket.socket, media: OpenedMedia, *,
                  kiosk_uid: int) -> None:
    """Transfer one media FD. Caller must recheck current authorization first.

    SCM_RIGHTS duplicates the underlying open file into the receiver. This
    function does not close the sender-owned FD: caller must close it in
    finally, regardless of outcome. No paths, epochs or arbitrary commands
    travel through the connection.
    """
    _packet_socket(conn)
    if peer_credentials(conn).uid != kiosk_uid:
        raise BrokerError("Unexpected receiving Unix account")
    if (not isinstance(media, OpenedMedia) or media.fd < 0
            or not _canonical_uuid(media.item_id)
            or type(media.playlist_revision) is not str
            or len(media.playlist_revision) != 64
            or any(ch not in "0123456789abcdef" for ch in media.playlist_revision)):
        raise BrokerError("Invalid verified media grant")
    try:
        info = os.fstat(media.fd)
    except OSError as exc:
        raise BrokerError("Media descriptor unavailable") from exc
    if (not stat.S_ISREG(info.st_mode) or info.st_ino != media.inode
            or info.st_dev != media.device):
        raise BrokerError("Media identity mismatch")
    payload = json.dumps({
        "version": 1, "item_id": media.item_id,
        "revision": media.playlist_revision,
    }, separators=(",", ":")).encode("ascii")
    if len(payload) > MAX_MESSAGE:
        raise BrokerError("Oversized handoff message")
    try:
        count = conn.sendmsg([payload], [(socket.SOL_SOCKET, socket.SCM_RIGHTS,
                                        array.array("i", [media.fd]))])
    except OSError as exc:
        raise BrokerError("Media handoff failed") from exc
    if count != len(payload):
        raise BrokerError("Incomplete media handoff")


def recv_video_fd(conn: socket.socket, *, broker_uid: int) -> ReceivedVideo:
    """Kiosk receives exactly one FD, rejecting truncated/untrusted frames.

    Caller owns and must close ReceivedVideo. No media path is accepted.
    """
    _packet_socket(conn)
    if peer_credentials(conn).uid != broker_uid:
        raise BrokerError("Unexpected sending Unix account")
    if not hasattr(socket, "MSG_CMSG_CLOEXEC"):
        raise BrokerError("Atomic close-on-exec receive is unavailable")
    fds = []
    try:
        payload, controls, flags, _ = conn.recvmsg(
            MAX_MESSAGE + 1, socket.CMSG_SPACE(4 * array.array("i").itemsize),
            socket.MSG_CMSG_CLOEXEC)
        for level, kind, value in controls:
            if level != socket.SOL_SOCKET or kind != socket.SCM_RIGHTS:
                raise BrokerError("Unexpected ancillary message")
            if len(value) % array.array("i").itemsize:
                raise BrokerError("Malformed descriptor control")
            arr = array.array("i")
            arr.frombytes(value)
            fds.extend(arr)
        if (flags & (socket.MSG_TRUNC | socket.MSG_CTRUNC) or
                len(payload) > MAX_MESSAGE or len(fds) != 1):
            raise BrokerError("Missing, truncated or duplicate media descriptor")
        try:
            body = json.loads(payload.decode("ascii"))
        except (ValueError, UnicodeError) as exc:
            raise BrokerError("Invalid media handoff JSON") from exc
        if (type(body) is not dict or set(body) != {"version", "item_id", "revision"}
                or type(body["version"]) is not int or body["version"] != 1
                or not _canonical_uuid(body["item_id"])
                or type(body["revision"]) is not str
                or len(body["revision"]) != 64
                or any(ch not in "0123456789abcdef" for ch in body["revision"])):
            raise BrokerError("Invalid media handoff contract")
        info = os.fstat(fds[0])
        if not stat.S_ISREG(info.st_mode):
            raise BrokerError("Received nonregular media")
        result = ReceivedVideo(fds.pop(), body["item_id"], body["revision"],
                               info.st_ino, info.st_dev)
        return result
    except (OSError, ValueError) as exc:
        if isinstance(exc, BrokerError):
            raise
        raise BrokerError("Unable to receive media descriptor") from exc
    finally:
        for fd in fds:
            os.close(fd)

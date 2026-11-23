"""Isolated Phase 2B-2 peer and media opening tests (no live IPC listener)."""
import os
import socket
import tempfile
import unittest
import uuid
from unittest.mock import patch

from pi_player.mpv_owner import OwnerLease
from pi_player.mpv_broker import (
    BrokerError, MediaRecord, OfflineMediaBroker, peer_credentials,
)


def ident():
    return str(uuid.uuid4())


@unittest.skipUnless(os.name == "posix" and hasattr(socket, "SO_PEERCRED"),
                     "Requires Linux Unix peer credentials")
class BrokerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.a, self.b = socket.socketpair(socket.AF_UNIX)
        self.addCleanup(self.a.close)
        self.addCleanup(self.b.close)
        self.broker = OfflineMediaBroker(
            self.tmp.name, kiosk_uid=os.getuid(), api_uid=os.getuid() + 10000)
        self.addCleanup(self.broker.close)
        self.lease = OwnerLease(ident(), "a" * 64)
        self.record = MediaRecord(ident(), "clip.mp4", "r1", True, True)
        with open(os.path.join(self.tmp.name, "clip.mp4"), "wb") as output:
            output.write(b"data")

    def test_kernel_credentials_not_claimed_by_client(self):
        peer = peer_credentials(self.a)
        self.assertEqual(peer.uid, os.getuid())
        self.assertGreater(peer.pid, 0)

    def test_safe_regular_video_fd(self):
        with self.broker.open_video(self.a, self.lease, self.record) as opened:
            self.assertEqual(os.read(opened.fd, 4), b"data")
            self.assertEqual(opened.owner_epoch, self.lease.epoch)
            self.assertEqual(opened.item_id, self.record.item_id)
            self.assertNotIn(self.lease.epoch, repr(opened))
        self.assertEqual(opened.fd, -1)

    def test_open_fd_survives_rename_and_replacement(self):
        with self.broker.open_video(self.a, self.lease, self.record) as opened:
            os.rename(os.path.join(self.tmp.name, "clip.mp4"),
                      os.path.join(self.tmp.name, "old.mp4"))
            with open(os.path.join(self.tmp.name, "clip.mp4"), "wb") as out:
                out.write(b"other")
            os.lseek(opened.fd, 0, os.SEEK_SET)
            self.assertEqual(os.read(opened.fd, 4), b"data")

    def test_reject_symlink_even_when_target_is_regular(self):
        os.unlink(os.path.join(self.tmp.name, "clip.mp4"))
        with open(os.path.join(self.tmp.name, "outside.mp4"), "wb") as out:
            out.write(b"outside")
        os.symlink("outside.mp4", os.path.join(self.tmp.name, "clip.mp4"))
        with self.assertRaises(BrokerError):
            self.broker.open_video(self.a, self.lease, self.record)

    def test_reject_filename_traversal_and_non_video(self):
        for name in ("../clip.mp4", "/etc/passwd", "nested/clip.mp4",
                     "clip.mp4/../x.mp4", ".hidden.mp4", "a\\b.mp4",
                     "clip.jpg", "é.mp4", ""):
            with self.subTest(name=name), self.assertRaises(BrokerError):
                self.broker.open_video(
                    self.a, self.lease,
                    MediaRecord(ident(), name, "r1", True, True))

    def test_reject_other_uid(self):
        other = OfflineMediaBroker(self.tmp.name, kiosk_uid=os.getuid()+1,
                                   api_uid=os.getuid())
        self.addCleanup(other.close)
        with self.assertRaises(BrokerError):
            other.open_video(self.a, self.lease, self.record)

    def test_unsafe_same_uid_configuration_rejected(self):
        with self.assertRaises(BrokerError):
            OfflineMediaBroker(self.tmp.name, kiosk_uid=os.getuid(),
                               api_uid=os.getuid())

    def test_reject_disabled_and_nonvideo_records(self):
        for enabled, video in ((False, True), (True, False), (1, True)):
            with self.subTest(enabled=enabled, video=video):
                with self.assertRaises(BrokerError):
                    self.broker.open_video(
                        self.a, self.lease,
                        MediaRecord(ident(), "clip.mp4", "r1", enabled, video))

    def test_reject_invalid_lease_and_media_id(self):
        with self.assertRaises(BrokerError):
            self.broker.open_video(
                self.a, OwnerLease(ident(), "é"*64), self.record)
        with self.assertRaises(BrokerError):
            self.broker.open_video(
                self.a, self.lease,
                MediaRecord("bad", "clip.mp4", "r1", True, True))

    def test_reject_non_socket_peer(self):
        with self.assertRaises(BrokerError):
            self.broker.open_video(None, self.lease, self.record)

    def test_reject_fifo_without_blocking(self):
        os.unlink(os.path.join(self.tmp.name, "clip.mp4"))
        os.mkfifo(os.path.join(self.tmp.name, "clip.mp4"))
        with self.assertRaises(BrokerError):
            self.broker.open_video(self.a, self.lease, self.record)

    def test_closed_broker_denies_new_open(self):
        self.broker.close()
        with self.assertRaises(BrokerError):
            self.broker.open_video(self.a, self.lease, self.record)

    def test_invalid_root_rejected(self):
        with self.assertRaises(BrokerError):
            OfflineMediaBroker("relative/path", kiosk_uid=100, api_uid=101)
        with self.assertRaises(BrokerError):
            OfflineMediaBroker(self.tmp.name, kiosk_uid=True, api_uid=101)


if __name__ == "__main__":
    unittest.main()

"""Real Linux Unix seqpacket SCM_RIGHTS contract tests (no listener)."""
import os
import socket
import tempfile
import unittest
import uuid

from pi_player.mpv_broker import BrokerError, OpenedMedia
from pi_player.mpv_fd_transport import send_video_fd, recv_video_fd


@unittest.skipUnless(os.name == "posix" and hasattr(socket, "SO_PEERCRED")
                     and hasattr(socket, "SOCK_SEQPACKET")
                     and hasattr(socket, "MSG_CMSG_CLOEXEC"),
                     "Linux Unix SCM_RIGHTS required")
class HandoffTests(unittest.TestCase):
    def setUp(self):
        self.a, self.b = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        self.addCleanup(self.a.close)
        self.addCleanup(self.b.close)
        self.tmp = tempfile.TemporaryFile()
        self.addCleanup(self.tmp.close)
        self.tmp.write(b"test-video-content")
        self.tmp.flush()
        self.tmp.seek(0)
        stat_info = os.fstat(self.tmp.fileno())
        self.media = OpenedMedia(os.dup(self.tmp.fileno()), str(uuid.uuid4()),
                                 "b" * 64, "a" * 64,
                                 stat_info.st_ino, stat_info.st_dev)
        self.addCleanup(self.media.close)

    def test_transfer_has_independent_lifetime(self):
        send_video_fd(self.a, self.media, kiosk_uid=os.getuid())
        with recv_video_fd(self.b, broker_uid=os.getuid()) as received:
            self.media.close()
            self.assertEqual(os.read(received.fd, 18), b"test-video-content")
            self.assertEqual(received.item_id, self.media.item_id)
            self.assertFalse(os.get_inheritable(received.fd))
        self.assertEqual(received.fd, -1)

    def test_broker_uid_mismatch_denies_and_does_not_consume_packet(self):
        send_video_fd(self.a, self.media, kiosk_uid=os.getuid())
        with self.assertRaises(BrokerError):
            recv_video_fd(self.b, broker_uid=os.getuid()+100)
        with recv_video_fd(self.b, broker_uid=os.getuid()) as received:
            self.assertGreaterEqual(received.fd, 0)

    def test_kiosk_uid_mismatch_denies_before_send(self):
        with self.assertRaises(BrokerError):
            send_video_fd(self.a, self.media, kiosk_uid=os.getuid()+100)
        self.b.settimeout(0.05)
        with self.assertRaises(socket.timeout):
            self.b.recv(1)

    def test_bad_json_with_fd_closes_received_descriptor(self):
        import array
        self.a.sendmsg([b"{}"], [(socket.SOL_SOCKET, socket.SCM_RIGHTS,
                                   array.array("i", [self.media.fd]))])
        with self.assertRaises(BrokerError):
            recv_video_fd(self.b, broker_uid=os.getuid())

    def test_missing_fd_rejected(self):
        self.a.send(b'{"version":1,"item_id":"not-uuid","revision":"bad"}')
        with self.assertRaises(BrokerError):
            recv_video_fd(self.b, broker_uid=os.getuid())

    def test_sender_descriptor_cannot_be_closed_prior_to_handoff(self):
        self.media.close()
        with self.assertRaises(BrokerError):
            send_video_fd(self.a, self.media, kiosk_uid=os.getuid())


if __name__ == "__main__":
    unittest.main()

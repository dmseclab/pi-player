"""Offline coordinator end-to-end SQLite and Unix handoff tests."""
import hashlib
import os
import socket
import sqlite3
import tempfile
import unittest
import uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from pi_player.db import install_playback_generation
from pi_player.mpv_broker import BrokerError, OfflineMediaBroker
from pi_player.mpv_fd_transport import recv_video_fd
from pi_player.mpv_handoff import OfflineHandoffCoordinator
from pi_player.mpv_owner import OfflineOwner


@unittest.skipUnless(os.name == "posix" and hasattr(socket, "SO_PEERCRED")
                     and hasattr(socket, "SOCK_SEQPACKET")
                     and hasattr(socket, "MSG_CMSG_CLOEXEC"),
                     "Linux authenticated Unix FD handoff required")
class CoordinatorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.dbfile = str(root / "state.sqlite")
        db = sqlite3.connect(self.dbfile)
        db.executescript("""
        CREATE TABLE playlists (id TEXT PRIMARY KEY, is_active INTEGER, updated_at TEXT);
        CREATE TABLE assets (id TEXT PRIMARY KEY, type TEXT, storage_path TEXT,
            mime_type TEXT, size_bytes INTEGER, checksum_sha256 TEXT,
            updated_at TEXT, deleted_at TEXT, display_mode TEXT,
            video_muted INTEGER, video_loop INTEGER);
        CREATE TABLE playlist_items (id TEXT PRIMARY KEY, playlist_id TEXT,
            asset_id TEXT, enabled INTEGER, updated_at TEXT,
            schedule_enabled INTEGER, schedule_mode TEXT,
            schedule_start_date TEXT, schedule_end_date TEXT,
            schedule_weekdays TEXT, schedule_start_time TEXT,
            schedule_end_time TEXT, position INTEGER, duration_seconds INTEGER);
        CREATE TABLE playback_state (id INTEGER PRIMARY KEY,
            playlist_id TEXT, item_id TEXT, state TEXT, updated_at TEXT);
        """)
        self.playlist, self.item, self.asset = (str(uuid.uuid4()) for _ in range(3))
        filename = self.asset + ".mp4"
        data = b"known-video-bytes"
        (root / filename).write_bytes(data)
        db.execute("INSERT INTO playlists VALUES (?,1,'p1')", (self.playlist,))
        db.execute("INSERT INTO assets VALUES (?,?,?,?,?,?,?,NULL,'fit',1,0)",
                   (self.asset, "video", str(root / filename), "video/mp4",
                    len(data), hashlib.sha256(data).hexdigest(), "a1"))
        db.execute("""INSERT INTO playlist_items VALUES
                   (?,?,?,?,?,0,'recurring',NULL,NULL,NULL,NULL,NULL,0,15)""",
                   (self.item, self.playlist, self.asset, 1, "i1"))
        db.execute("INSERT INTO playback_state VALUES (1,?,NULL,'playing','s1')",
                   (self.playlist,))
        install_playback_generation(db)
        db.commit()
        db.close()
        self.a, self.b = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        self.addCleanup(self.a.close)
        self.addCleanup(self.b.close)
        self.broker = OfflineMediaBroker(self.tmp.name,
                                         kiosk_uid=os.getuid(),
                                         api_uid=os.getuid() + 9000)
        self.addCleanup(self.broker.close)
        self.owner = OfflineOwner()
        self.coordinator = OfflineHandoffCoordinator(
            broker=self.broker, owner=self.owner,
            connection_factory=lambda: sqlite3.connect(self.dbfile),
            asset_root=self.tmp.name)
        self.lease = self.coordinator.bind_kiosk(self.a, str(uuid.uuid4()))
        self.now = datetime(2026, 11, 23, 12, 0,
                            tzinfo=ZoneInfo("Africa/Johannesburg"))

    def test_fresh_video_handoff(self):
        self.coordinator.handoff(self.a, self.lease, self.item, now=self.now)
        with recv_video_fd(self.b, broker_uid=os.getuid()) as received:
            self.assertEqual(os.read(received.fd, 17), b"known-video-bytes")
            self.assertEqual(received.item_id, self.item)

    def test_stopped_playback_refuses_handoff(self):
        with sqlite3.connect(self.dbfile) as db:
            db.execute("UPDATE playback_state SET state='stopped' WHERE id=1")
        with self.assertRaises(BrokerError):
            self.coordinator.handoff(self.a, self.lease, self.item, now=self.now)

    def test_disconnect_revokes_owner(self):
        self.coordinator.disconnect(self.a)
        with self.assertRaises(BrokerError):
            self.coordinator.handoff(self.a, self.lease, self.item, now=self.now)

    def test_replaced_owner_cannot_handoff(self):
        old = self.lease
        self.lease = self.coordinator.bind_kiosk(self.a, str(uuid.uuid4()))
        with self.assertRaises(BrokerError):
            self.coordinator.handoff(self.a, old, self.item, now=self.now)

    def test_content_tamper_denied(self):
        file = Path(self.tmp.name) / (self.asset + ".mp4")
        file.write_bytes(b"altered-video!!!")
        with self.assertRaises(BrokerError):
            self.coordinator.handoff(self.a, self.lease, self.item, now=self.now)


if __name__ == "__main__":
    unittest.main()

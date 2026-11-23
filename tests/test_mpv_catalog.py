"""Phase 2B-2 catalog read-only authorization tests; no web or Pi."""
import hashlib
import os
import sqlite3
import tempfile
import unittest
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

from pi_player.mpv_catalog import lookup_video, _allowed_schedule, check_opened_media
from pi_player.mpv_broker import BrokerError, OpenedMedia

TZ = ZoneInfo("Africa/Johannesburg")


def uid():
    return str(uuid.uuid4())


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.conn = sqlite3.connect(":memory:")
        self.addCleanup(self.conn.close)
        self.conn.executescript("""
        CREATE TABLE playlists (id TEXT, is_active INTEGER, updated_at TEXT);
        CREATE TABLE assets (id TEXT, type TEXT, storage_path TEXT,
            mime_type TEXT, size_bytes INTEGER, checksum_sha256 TEXT,
            updated_at TEXT, deleted_at TEXT);
        CREATE TABLE playlist_items (id TEXT, playlist_id TEXT, asset_id TEXT,
            enabled INTEGER, updated_at TEXT, schedule_enabled INTEGER,
            schedule_mode TEXT, schedule_start_date TEXT, schedule_end_date TEXT,
            schedule_weekdays TEXT, schedule_start_time TEXT, schedule_end_time TEXT);
        """)
        self.item, self.asset, self.playlist = uid(), uid(), uid()
        self.filename = self.asset + ".mp4"
        self.path = os.path.join(self.tmp.name, self.filename)
        with open(self.path, "wb") as stream:
            stream.write(b"video-test-content")
        self.digest = hashlib.sha256(b"video-test-content").hexdigest()
        self.conn.execute("INSERT INTO playlists VALUES (?,1,'p1')", (self.playlist,))
        self.conn.execute("INSERT INTO assets VALUES (?,?,?,?,?,?,?,NULL)",
                          (self.asset, "video", self.path, "video/mp4",
                           len(b"video-test-content"), self.digest, "a1"))
        self.conn.execute("""INSERT INTO playlist_items VALUES
            (?,?,?,?,?,0,'recurring',NULL,NULL,NULL,NULL,NULL)""",
                          (self.item, self.playlist, self.asset, 1, "i1"))
        self.now = datetime(2026, 11, 23, 10, 0, tzinfo=TZ)

    def lookup(self):
        return lookup_video(self.conn, self.item, asset_root=self.tmp.name, now=self.now)

    def test_active_video_is_eligible(self):
        grant = self.lookup()
        self.assertEqual(grant.record.item_id, self.item)
        self.assertEqual(grant.record.filename, self.filename)
        self.assertEqual(len(grant.revision), 64)

    def test_disabled_item_rejected(self):
        self.conn.execute("UPDATE playlist_items SET enabled=0")
        with self.assertRaises(BrokerError):
            self.lookup()

    def test_deleted_asset_rejected(self):
        self.conn.execute("UPDATE assets SET deleted_at='deleted'")
        with self.assertRaises(BrokerError):
            self.lookup()

    def test_inactive_playlist_rejected(self):
        self.conn.execute("UPDATE playlists SET is_active=0")
        with self.assertRaises(BrokerError):
            self.lookup()

    def test_wrong_item_rejected(self):
        with self.assertRaises(BrokerError):
            lookup_video(self.conn, uid(), asset_root=self.tmp.name, now=self.now)

    def test_nonvideo_asset_rejected(self):
        self.conn.execute("UPDATE assets SET type='image'")
        with self.assertRaises(BrokerError):
            self.lookup()

    def test_missing_checksum_rejected(self):
        self.conn.execute("UPDATE assets SET checksum_sha256=NULL")
        with self.assertRaises(BrokerError):
            self.lookup()

    def test_mismatched_storage_path_rejected(self):
        self.conn.execute("UPDATE assets SET storage_path='/tmp/elsewhere.mp4'")
        with self.assertRaises(BrokerError):
            self.lookup()

    def test_revision_changes_with_playlist_item_or_asset(self):
        old = self.lookup().revision
        self.conn.execute("UPDATE playlist_items SET updated_at='i2'")
        self.assertNotEqual(old, self.lookup().revision)
        newer = self.lookup().revision
        self.conn.execute("UPDATE assets SET updated_at='a2'")
        self.assertNotEqual(newer, self.lookup().revision)

    def test_window_schedule_rejects_outside_interval(self):
        self.conn.execute("""UPDATE playlist_items SET schedule_enabled=1,
            schedule_mode='window', schedule_start_date='2026-11-24',
            schedule_end_date='2026-11-25', schedule_start_time='09:00',
            schedule_end_time='17:00'""")
        with self.assertRaises(BrokerError):
            self.lookup()

    def test_recurring_overnight_previous_weekday(self):
        item = dict(schedule_enabled=1, schedule_mode="recurring",
                    schedule_start_date=None, schedule_end_date=None,
                    schedule_weekdays="0", schedule_start_time="23:00",
                    schedule_end_time="07:00")
        self.assertTrue(_allowed_schedule(
            item, datetime(2026, 11, 24, 1, 0, tzinfo=TZ)))
        self.assertFalse(_allowed_schedule(
            item, datetime(2026, 11, 25, 1, 0, tzinfo=TZ)))

    def test_descriptor_checksum_and_mutation_detection(self):
        grant = self.lookup()
        fd = os.open(self.path, os.O_RDONLY)
        opened = OpenedMedia(fd, self.item, grant.revision, "a"*64, 0, 0)
        try:
            check_opened_media(opened, grant)
            with open(self.path, "r+b") as out:
                out.write(b"tamper")
            with self.assertRaises(BrokerError):
                check_opened_media(opened, grant)
        finally:
            opened.close()


if __name__ == "__main__":
    unittest.main()

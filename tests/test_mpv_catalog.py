"""Phase 2B-2 catalog read-only authorization tests; no web or Pi."""
import hashlib
import os
import sqlite3
import tempfile
import unittest
import uuid
from unittest.mock import patch
from types import SimpleNamespace
from datetime import datetime
from zoneinfo import ZoneInfo

from pi_player.mpv_catalog import lookup_video, _allowed_schedule, check_opened_media
from pi_player.mpv_broker import BrokerError, OpenedMedia
from pi_player.db import install_playback_generation

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
            updated_at TEXT, deleted_at TEXT,
            display_mode TEXT, video_muted INTEGER, video_loop INTEGER);
        CREATE TABLE playlist_items (id TEXT, playlist_id TEXT, asset_id TEXT,
            enabled INTEGER, updated_at TEXT, schedule_enabled INTEGER,
            schedule_mode TEXT, schedule_start_date TEXT, schedule_end_date TEXT,
            schedule_weekdays TEXT, schedule_start_time TEXT, schedule_end_time TEXT,
            position INTEGER, duration_seconds INTEGER);
        CREATE TABLE playback_state (id INTEGER, playlist_id TEXT, item_id TEXT,
            state TEXT, updated_at TEXT);
        """)
        self.item, self.asset, self.playlist = uid(), uid(), uid()
        self.filename = self.asset + ".mp4"
        self.path = os.path.join(self.tmp.name, self.filename)
        with open(self.path, "wb") as stream:
            stream.write(b"video-test-content")
        self.digest = hashlib.sha256(b"video-test-content").hexdigest()
        self.conn.execute("INSERT INTO playlists VALUES (?,1,'p1')", (self.playlist,))
        self.conn.execute("INSERT INTO assets VALUES (?,?,?,?,?,?,?,NULL,'fit',1,0)",
                          (self.asset, "video", self.path, "video/mp4",
                           len(b"video-test-content"), self.digest, "a1"))
        self.conn.execute("""INSERT INTO playlist_items VALUES
            (?,?,?,?,?,0,'recurring',NULL,NULL,NULL,NULL,NULL,0,15)""",
                          (self.item, self.playlist, self.asset, 1, "i1"))
        self.conn.execute("INSERT INTO playback_state VALUES (1, ?, NULL, 'playing', 's1')",
                          (self.playlist,))
        install_playback_generation(self.conn)
        self.now = datetime(2026, 11, 23, 10, 0, tzinfo=TZ)

    def lookup(self):
        return lookup_video(self.conn, self.item, asset_root=self.tmp.name, now=self.now)

    def test_active_video_is_eligible(self):
        grant = self.lookup()
        self.assertEqual(grant.record.item_id, self.item)
        self.assertEqual(grant.record.filename, self.filename)
        self.assertEqual(len(grant.revision), 64)

    def test_stop_restart_fixed_timestamp_changes_generation_and_revision(self):
        before = self.lookup().revision
        initial = self.conn.execute(
            "SELECT playback_generation FROM playback_state WHERE id=1").fetchone()[0]
        # These SQL updates are identical in shape to the production API
        # statements; preserve an identical wall-clock timestamp.
        self.conn.execute(
            "UPDATE playback_state SET state='stopped',updated_at='s1' WHERE id=1")
        with self.assertRaises(BrokerError):
            self.lookup()
        self.conn.execute(
            "UPDATE playback_state SET playlist_id=?,state='playing',updated_at='s1' WHERE id=1",
            (self.playlist,))
        after = self.lookup().revision
        final = self.conn.execute(
            "SELECT playback_generation FROM playback_state WHERE id=1").fetchone()[0]
        self.assertEqual(final, initial + 2)
        self.assertNotEqual(before, after)

    def test_start_again_same_second_is_a_new_generation(self):
        original = self.lookup().revision
        self.conn.execute(
            "UPDATE playback_state SET playlist_id=?,state='playing',updated_at='s1' WHERE id=1",
            (self.playlist,))
        self.assertNotEqual(original, self.lookup().revision)

    def test_generation_install_idempotent_and_old_schema_fail_closed(self):
        before = self.lookup().revision
        install_playback_generation(self.conn)
        self.assertEqual(before, self.lookup().revision)
        self.conn.execute(
            "UPDATE playback_state SET state='stopped',updated_at='s1' WHERE id=1")
        count = self.conn.execute(
            "SELECT playback_generation FROM playback_state WHERE id=1").fetchone()[0]
        self.assertEqual(count, 1)
        self.conn.execute("DROP TRIGGER playback_state_bump_generation")
        self.conn.execute("UPDATE playback_state SET state='playing',updated_at='s1' WHERE id=1")
        # Missing trigger is not an acceptable deployed configuration:
        # this test documents why initialization must always install it.
        self.assertEqual(self.conn.execute(
            "SELECT playback_generation FROM playback_state WHERE id=1").fetchone()[0], 1)

    def test_generation_invalid_metadata_rejected(self):
        self.conn.execute(
            "UPDATE playback_state SET playback_generation=-1 WHERE id=1")
        with self.assertRaises(BrokerError):
            self.lookup()
        self.conn.execute(
            "UPDATE playback_state SET playback_generation=? WHERE id=1",
            (sqlite3.Binary(b"invalid"),))
        with self.assertRaises(BrokerError):
            self.lookup()

    def test_stopped_or_missing_playback_denied(self):
        self.conn.execute("UPDATE playback_state SET state='stopped'")
        with self.assertRaises(BrokerError):
            self.lookup()
        self.conn.execute("DELETE FROM playback_state")
        with self.assertRaises(BrokerError):
            self.lookup()

    def test_ambiguous_or_inconsistent_playback_denied(self):
        self.conn.execute("INSERT INTO playlists VALUES (?,1,'p2')", (uid(),))
        with self.assertRaises(BrokerError):
            self.lookup()
        self.conn.execute("DELETE FROM playlists WHERE updated_at='p2'")
        self.conn.execute("UPDATE playback_state SET playlist_id=?", (uid(),))
        with self.assertRaises(BrokerError):
            self.lookup()
        self.conn.execute("UPDATE playback_state SET playlist_id=?", (self.playlist,))
        self.conn.execute("INSERT INTO playback_state VALUES (2, ?, NULL, 'playing', 's2')",
                          (self.playlist,))
        with self.assertRaises(BrokerError):
            self.lookup()

    def test_same_second_playback_settings_change_revision(self):
        previous = self.lookup().revision
        self.conn.execute("UPDATE playlist_items SET duration_seconds=44")
        changed = self.lookup().revision
        self.assertNotEqual(previous, changed)
        self.conn.execute("UPDATE assets SET video_loop=1")
        loop = self.lookup().revision
        self.assertNotEqual(changed, loop)
        self.conn.execute("UPDATE assets SET video_muted=0")
        muted = self.lookup().revision
        self.assertNotEqual(loop, muted)
        self.conn.execute("UPDATE playback_state SET updated_at='s2'")
        self.assertNotEqual(muted, self.lookup().revision)

    def test_bad_revision_blob_fails_closed(self):
        self.conn.execute("UPDATE playlist_items SET updated_at=?", (sqlite3.Binary(b"bad"),))
        with self.assertRaises(BrokerError):
            self.lookup()

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

    @unittest.skipUnless(hasattr(os, "pread"), "POSIX positional read required")
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


    @unittest.skipUnless(hasattr(os, "pread"), "POSIX positional read required")
    def test_same_size_metadata_change_during_hash_is_denied(self):
        grant = self.lookup()
        fd = os.open(self.path, os.O_RDONLY)
        opened = OpenedMedia(fd, self.item, grant.revision, "a"*64, 0, 0)
        original = os.fstat
        calls = 0
        def changed_second_stat(target):
            nonlocal calls
            result = original(target)
            if target == fd:
                calls += 1
                if calls == 2:
                    return SimpleNamespace(
                        st_dev=result.st_dev, st_ino=result.st_ino,
                        st_size=result.st_size, st_mtime_ns=result.st_mtime_ns + 1,
                        st_ctime_ns=result.st_ctime_ns + 1)
            return result
        try:
            with patch("pi_player.mpv_catalog.os.fstat", side_effect=changed_second_stat):
                with self.assertRaisesRegex(BrokerError, "changed during verification"):
                    check_opened_media(opened, grant)
            self.assertEqual(calls, 2)
        finally:
            opened.close()


if __name__ == "__main__":
    unittest.main()

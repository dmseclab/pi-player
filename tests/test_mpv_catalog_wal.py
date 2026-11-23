"""Real SQLite WAL tests for catalog snapshot and trigger repair behavior.

Offline, independent connections; never touches the live Pi Player database.
"""
import hashlib
import os
import sqlite3
import tempfile
import unittest
import uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from pi_player.db import install_playback_generation, playback_generation_trigger_valid
from pi_player.mpv_broker import BrokerError
from pi_player.mpv_catalog import lookup_video


class WalGenerationTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.asset_root = self.folder.name
        self.db_file = str(Path(self.folder.name) / "wal-check.sqlite")
        self.a = sqlite3.connect(self.db_file, timeout=5)
        self.addCleanup(self.a.close)
        self.assertEqual(self.a.execute("PRAGMA journal_mode=WAL").fetchone()[0], "wal")
        self.a.execute("PRAGMA busy_timeout=5000")
        self.a.executescript("""
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
        self.filename = self.asset + ".mp4"
        self.content = b"fixture media content"
        self.asset_path = os.path.join(self.asset_root, self.filename)
        with open(self.asset_path, "wb") as stream:
            stream.write(self.content)
        self.a.execute("INSERT INTO playlists VALUES (?,1,'p1')", (self.playlist,))
        self.a.execute("INSERT INTO assets VALUES (?,?,?,?,?,?,?,NULL,'fit',1,0)",
                       (self.asset, "video", self.asset_path, "video/mp4",
                        len(self.content), hashlib.sha256(self.content).hexdigest(), "a1"))
        self.a.execute("""INSERT INTO playlist_items VALUES
            (?,?,?,?,?,0,'recurring',NULL,NULL,NULL,NULL,NULL,0,15)""",
            (self.item, self.playlist, self.asset, 1, "i1"))
        self.a.execute("INSERT INTO playback_state VALUES (1,?,NULL,'playing','fixed')",
                       (self.playlist,))
        install_playback_generation(self.a)
        self.a.commit()
        self.b = sqlite3.connect(self.db_file, timeout=5)
        self.addCleanup(self.b.close)
        self.b.execute("PRAGMA busy_timeout=5000")
        self.now = datetime(2026, 11, 23, 12, 0,
                            tzinfo=ZoneInfo("Africa/Johannesburg"))

    def lookup(self, conn):
        return lookup_video(conn, self.item, asset_root=self.asset_root, now=self.now)

    def generation(self, conn):
        return conn.execute(
            "SELECT playback_generation FROM playback_state WHERE id=1").fetchone()[0]

    def drop_and_replay(self):
        self.b.execute("DROP TRIGGER playback_state_bump_generation")
        self.b.execute(
            "UPDATE playback_state SET state='stopped',updated_at='fixed' WHERE id=1")
        self.b.execute(
            "UPDATE playback_state SET state='playing',updated_at='fixed' WHERE id=1")
        self.b.commit()

    def test_wal_new_statement_after_trigger_removed_denies(self):
        old = self.lookup(self.a).revision
        self.drop_and_replay()
        # The missing trigger and the row both belong to this new statement's
        # snapshot. No stale prior trigger check may authorize this row.
        with self.assertRaises(BrokerError):
            self.lookup(self.a)
        self.assertEqual(self.generation(self.a), 0)
        self.assertTrue(old)

    def test_wal_pinned_reader_snapshot_does_not_mix_schema_versions(self):
        old = self.lookup(self.a).revision
        self.a.execute("BEGIN")
        self.a.execute("SELECT id FROM playback_state WHERE id=1").fetchone()
        self.drop_and_replay()
        # A snapshot pinned before the writer commits is internally
        # consistent. An old grant here is NOT handoff-time authorization.
        try:
            self.assertEqual(self.lookup(self.a).revision, old)
        finally:
            self.a.rollback()
        with self.assertRaises(BrokerError):
            self.lookup(self.a)

    def test_wal_repair_invalidates_pre_removal_revision(self):
        old = self.lookup(self.a).revision
        self.drop_and_replay()
        with self.assertRaises(BrokerError):
            self.lookup(self.a)
        before = self.generation(self.b)
        install_playback_generation(self.b)
        self.b.commit()
        self.assertTrue(playback_generation_trigger_valid(self.a))
        self.assertEqual(self.generation(self.a), before + 1)
        self.assertNotEqual(self.lookup(self.a).revision, old)

    def test_wal_repair_is_atomic_and_idempotent(self):
        before = self.lookup(self.a).revision
        install_playback_generation(self.b)
        self.b.commit()
        self.assertEqual(self.lookup(self.a).revision, before)
        self.assertEqual(self.generation(self.a), 0)
        self.drop_and_replay()
        install_playback_generation(self.b)
        # Until commit, the other reader must not observe a partial repair.
        with self.assertRaises(BrokerError):
            self.lookup(self.a)
        self.b.rollback()
        with self.assertRaises(BrokerError):
            self.lookup(self.a)
        self.assertEqual(self.generation(self.a), 0)
        install_playback_generation(self.b)
        self.b.commit()
        self.assertEqual(self.generation(self.a), 1)

    def test_failed_repair_rolls_back_without_recreating_trigger(self):
        self.drop_and_replay()
        self.b.execute(
            "UPDATE playback_state SET playback_generation=9223372036854775807 WHERE id=1")
        self.b.commit()
        with self.assertRaises(RuntimeError):
            install_playback_generation(self.b)
        self.b.rollback()
        self.assertFalse(playback_generation_trigger_valid(self.b))
        with self.assertRaises(BrokerError):
            self.lookup(self.a)

    def test_wal_generation_after_repair_advances_each_transition(self):
        self.drop_and_replay()
        install_playback_generation(self.b)
        self.b.commit()
        current = self.generation(self.a)
        self.b.execute(
            "UPDATE playback_state SET state='stopped',updated_at='fixed' WHERE id=1")
        self.b.execute(
            "UPDATE playback_state SET state='playing',updated_at='fixed' WHERE id=1")
        self.b.commit()
        self.assertEqual(self.generation(self.a), current + 2)


if __name__ == "__main__":
    unittest.main()

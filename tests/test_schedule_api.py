"""Isolated database/API scheduling acceptance tests (no production DB, no pytest).

Run with PI_PLAYER_DATA_DIR set to a disposable directory, using application venv.
"""
import contextlib
import sqlite3
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from pydantic import ValidationError

from pi_player import scheduling


class SchedulingDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="pi-player-schedule-db-")
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "test.sqlite3"
        with self.connect() as conn:
            conn.executescript("""
                CREATE TABLE playlists (id TEXT PRIMARY KEY, name TEXT);
                CREATE TABLE assets (
                    id TEXT PRIMARY KEY, name TEXT, type TEXT,
                    deleted_at TEXT
                );
                CREATE TABLE playlist_items (
                    id TEXT PRIMARY KEY, playlist_id TEXT, asset_id TEXT,
                    position INTEGER, duration_seconds INTEGER, enabled INTEGER,
                    created_at TEXT, updated_at TEXT,
                    schedule_enabled INTEGER DEFAULT 0,
                    schedule_mode TEXT DEFAULT 'recurring',
                    schedule_start_date TEXT,
                    schedule_end_date TEXT,
                    schedule_weekdays TEXT,
                    schedule_start_time TEXT,
                    schedule_end_time TEXT
                );
                INSERT INTO playlists VALUES ('p1','Test');
                INSERT INTO assets VALUES ('asset1','Asset 1','image',NULL);
                INSERT INTO assets VALUES ('asset2','Asset 2','image',NULL);
                INSERT INTO playlist_items
                    (id,playlist_id,asset_id,position,duration_seconds,enabled,created_at,updated_at)
                    VALUES ('item1','p1','asset1',0,15,1,'initial','initial');
                INSERT INTO playlist_items
                    (id,playlist_id,asset_id,position,duration_seconds,enabled,created_at,updated_at)
                    VALUES ('item2','p1','asset2',1,15,1,'initial','initial');
            """)

    @contextlib.contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def update(self, item, payload):
        with patch.object(scheduling, "db", self.connect), \
             patch.object(scheduling, "_ensure_playlist_item", lambda *a: None), \
             patch.object(scheduling, "audit", lambda *a: None):
            return scheduling.update_scheduled_playlist_item(
                "p1", item,
                scheduling.ScheduledPlaylistItemUpdate.model_validate(payload),
                "test-user",
            )

    def get_item(self, item):
        with self.connect() as conn:
            return dict(conn.execute(
                "SELECT * FROM playlist_items WHERE id=?", (item,)
            ).fetchone())

    @staticmethod
    def valid_payload():
        return {
            "schedule_enabled": True, "schedule_mode": "window",
            "schedule_start_date": "2027-02-01",
            "schedule_start_time": "06:00",
            "schedule_end_date": "2027-02-03",
            "schedule_end_time": "18:00",
        }

    def test_save_reload_and_independence(self):
        before = self.get_item("item2")
        result = self.update("item1", self.valid_payload())
        stored = self.get_item("item1")
        self.assertEqual(stored["schedule_mode"], "window")
        self.assertEqual(stored["schedule_start_time"], "06:00")
        self.assertEqual(stored["schedule_end_time"], "18:00")
        self.assertEqual(self.get_item("item2"), before)
        self.assertEqual(len(result["items"]), 2)

    def test_reject_missing_start_or_end(self):
        for missing in (
            "schedule_start_date", "schedule_end_date",
            "schedule_start_time", "schedule_end_time",
        ):
            with self.subTest(missing=missing):
                payload = self.valid_payload()
                del payload[missing]
                with self.assertRaises(HTTPException) as raised:
                    self.update("item1", payload)
                self.assertEqual(raised.exception.status_code, 400)
                self.assertEqual(self.get_item("item1")["schedule_enabled"], 0)

    def test_reject_reversed_or_zero_length_window(self):
        invalid = [
            {"schedule_start_date": "2027-02-04"},
            {"schedule_end_date": "2027-01-31"},
            {"schedule_end_date": "2027-02-01", "schedule_end_time": "06:00"},
        ]
        for changes in invalid:
            with self.subTest(changes=changes):
                payload = {**self.valid_payload(), **changes}
                with self.assertRaises(HTTPException):
                    self.update("item1", payload)
                self.assertEqual(self.get_item("item1")["schedule_enabled"], 0)

    def test_invalid_modes_and_weekdays_rejected(self):
        for payload in (
            {"schedule_mode": "unknown"},
            {"schedule_weekdays": [7]},
            {"schedule_start_time": "99:99"},
        ):
            with self.subTest(payload=payload):
                with self.assertRaises(ValidationError):
                    scheduling.ScheduledPlaylistItemUpdate.model_validate(payload)

    def test_expired_item_only_disabled_and_asset_retained(self):
        self.update("item1", self.valid_payload())
        with self.connect() as conn:
            rows = [dict(r) for r in conn.execute("SELECT * FROM playlist_items ORDER BY id")]
            scheduling._expire_finite_schedules(conn, rows, datetime(2027, 2, 3, 18, 0))
        first = self.get_item("item1")
        second = self.get_item("item2")
        self.assertEqual(first["enabled"], 0)
        self.assertEqual(first["schedule_enabled"], 0)
        self.assertEqual(first["schedule_mode"], "recurring")
        self.assertIsNone(first["schedule_end_date"])
        self.assertEqual(second["enabled"], 1)
        with self.connect() as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM assets").fetchone()[0], 2)


if __name__ == "__main__":
    unittest.main()

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pi_player import db as db_module


class DefaultPlaylistInitializationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_patch = patch.object(db_module, "DB_PATH", Path(self.tmp.name) / "test.sqlite3")
        self.db_patch.start()
        self.addCleanup(self.db_patch.stop)

    def test_fresh_install_seeds_active_empty_default_playlist_once(self):
        db_module.init_db()
        with db_module.db() as conn:
            playlists = conn.execute("SELECT * FROM playlists").fetchall()
            self.assertEqual(len(playlists), 1)
            self.assertEqual(playlists[0]["name"], "Default")
            self.assertEqual(playlists[0]["is_active"], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM playlist_items").fetchone()[0], 0)
            playback = conn.execute("SELECT * FROM playback_state WHERE id = 1").fetchone()
            self.assertEqual(playback["playlist_id"], playlists[0]["id"])
            self.assertEqual(playback["state"], "stopped")

        db_module.init_db()
        with db_module.db() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM playlists").fetchone()[0], 1)
            conn.execute("DELETE FROM playlists")
        db_module.init_db()
        with db_module.db() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM playlists").fetchone()[0], 0)

    def test_existing_playlist_is_preserved_on_upgrade(self):
        db_module.init_db()
        with db_module.db() as conn:
            conn.execute("DELETE FROM playlists")
            conn.execute("DELETE FROM settings WHERE key='default_playlist_initialized'")
            conn.execute(
                "INSERT INTO playlists (id,name,is_active,created_at,updated_at)"
                " VALUES ('preexisting','Site Content',1,'2026-01-01','2026-01-01')"
            )
        db_module.init_db()
        with db_module.db() as conn:
            names = [r["name"] for r in conn.execute("SELECT name FROM playlists").fetchall()]
            self.assertEqual(names, ["Site Content"])


if __name__ == "__main__":
    unittest.main()

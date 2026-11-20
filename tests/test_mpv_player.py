"""Offline, hardware-independent tests for the opt-in MPV adapter."""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pi_player.mpv_player import MpvPlayer, validate_video_path


class FakeProcess:
    def __init__(self):
        self.returncode = None
        self.terminated = False

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True

    def wait(self, timeout=None):
        self.returncode = 0
        return 0


class MpvAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.assets = self.root / "assets"
        self.assets.mkdir()
        self.video = self.assets / "video.mp4"
        self.video.write_bytes(b"test")

    def test_reject_traversal_and_wrong_content_type(self):
        self.assertEqual(validate_video_path(self.video, self.assets), self.video)
        (self.root / "outside.mp4").write_bytes(b"test")
        with self.assertRaises(ValueError):
            validate_video_path(self.root / "outside.mp4", self.assets)
        (self.assets / "note.txt").write_text("text")
        with self.assertRaises(ValueError):
            validate_video_path(self.assets / "note.txt", self.assets)
        (self.assets / "escape.mp4").symlink_to(self.root / "outside.mp4")
        with self.assertRaises(ValueError):
            validate_video_path(self.assets / "escape.mp4", self.assets)

    def test_session_lifecycle_and_no_overlapping_process(self):
        p = FakeProcess()
        player = MpvPlayer(asset_dir=self.assets)
        with patch("pi_player.mpv_player.os.geteuid", return_value=os.getuid() or 1001), \
             patch.dict(os.environ, {"XDG_RUNTIME_DIR": str(self.root)}), \
             patch("pi_player.mpv_player.subprocess.Popen", return_value=p) as popen:
            session = player.start(self.video, muted=True)
            args = popen.call_args.args[0]
            self.assertIn("--hwdec=no", args)
            self.assertIn("--gpu-context=wayland", args)
            self.assertIn("--mute=yes", args)
            self.assertEqual(args[-1], str(self.video))
            with self.assertRaises(RuntimeError):
                player.start(self.video)
            self.assertFalse(player.stop("old-session"))
            self.assertFalse(p.terminated)
            self.assertTrue(player.stop(session))
            self.assertTrue(p.terminated)

    def test_reject_root(self):
        player = MpvPlayer(asset_dir=self.assets)
        with patch("pi_player.mpv_player.os.geteuid", return_value=0):
            with self.assertRaises(PermissionError):
                player.start(self.video)

    def test_exit_status_and_stale_id(self):
        p = FakeProcess()
        player = MpvPlayer(asset_dir=self.assets)
        with patch("pi_player.mpv_player.os.geteuid", return_value=os.getuid() or 1001), \
             patch.dict(os.environ, {"XDG_RUNTIME_DIR": str(self.root)}), \
             patch("pi_player.mpv_player.subprocess.Popen", return_value=p):
            session = player.start(self.video)
            p.returncode = 0
            self.assertTrue(player.status(session)["eof"])
            with self.assertRaises(ValueError):
                player.status("wrong")

    def test_hung_termination_keeps_session(self):
        p = FakeProcess()
        p.wait = lambda timeout=None: (_ for _ in ()).throw(subprocess.TimeoutExpired("mpv", timeout))
        player = MpvPlayer(asset_dir=self.assets)
        with patch("pi_player.mpv_player.os.geteuid", return_value=os.getuid() or 1001), \
             patch.dict(os.environ, {"XDG_RUNTIME_DIR": str(self.root)}), \
             patch("pi_player.mpv_player.subprocess.Popen", return_value=p):
            session = player.start(self.video)
            self.assertFalse(player.stop(session, timeout=0.1))
            with self.assertRaises(RuntimeError):
                player.start(self.video)


if __name__ == "__main__":
    unittest.main()

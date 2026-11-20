"""Offline tests for isolated MPV adapter, without launching media."""
import json
import os
import socket
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from pi_player.mpv_player import MpvPlayer, read_reply, validate_video_path


class FakeProcess:
    returncode = None

    def __init__(self):
        self.returncode = None
        self.terminated = False

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True

    def wait(self, timeout=None):
        self.returncode = 0


@unittest.skipUnless(hasattr(os, "geteuid"), "Unix-only process ownership")
class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.assets = self.root / "assets"
        self.assets.mkdir()
        self.video = self.assets / "video.mp4"
        self.video.write_bytes(b"dummy")

    def setup_player(self):
        player = MpvPlayer(asset_dir=self.assets)
        fake = FakeProcess()
        if os.getuid() == 0:
            self.skipTest("kiosk-UID lifecycle tests require an unprivileged Unix runner")
        with patch("pi_player.mpv_player.os.geteuid", return_value=os.getuid()), \
             patch.dict(os.environ, {"XDG_RUNTIME_DIR": str(self.root)}), \
             patch("pi_player.mpv_player.subprocess.Popen", return_value=fake):
            session = player.start(self.video)
        return player, fake, session

    def test_paths(self):
        self.assertEqual(validate_video_path(self.video, self.assets), self.video)
        (self.root / "outside.mp4").write_bytes(b"dummy")
        with self.assertRaises(ValueError):
            validate_video_path(self.root / "outside.mp4", self.assets)
        (self.assets / "escape.mp4").symlink_to(self.root / "outside.mp4")
        with self.assertRaises(ValueError):
            validate_video_path(self.assets / "escape.mp4", self.assets)

    def test_process_lifecycle_and_stale_ids(self):
        player, child, session = self.setup_player()
        with self.assertRaises(RuntimeError):
            with patch("pi_player.mpv_player.os.geteuid", return_value=os.getuid() or 1001):
                player.start(self.video)
        self.assertFalse(player.stop("stale"))
        self.assertTrue(player.stop(session))
        self.assertTrue(child.terminated)

    def test_exit_is_not_eof(self):
        player, child, session = self.setup_player()
        child.returncode = 0
        result = player.status(session)
        self.assertFalse(result["eof"])
        self.assertEqual(result["state"], "exited")
        self.assertEqual(result["exit_code"], 0)
        self.assertFalse(player.stop(session), "Session is already retired after observed exit")

    def test_ipc_unavailable_is_not_readiness(self):
        player, child, session = self.setup_player()
        result = player.status(session)
        self.assertEqual(result["state"], "starting")
        self.assertIsNone(result["position_seconds"])
        self.assertTrue(player.stop(session))

    def test_hung_termination_remains_tracked(self):
        player, child, session = self.setup_player()
        child.wait = lambda timeout=None: (_ for _ in ()).throw(subprocess.TimeoutExpired("mpv", timeout))
        self.assertFalse(player.stop(session, timeout=0.01))
        with patch("pi_player.mpv_player.os.geteuid", return_value=os.getuid() or 1001):
            with self.assertRaises(RuntimeError):
                player.start(self.video)
        child.returncode = 1
        self.assertTrue(player.stop(session))


    def test_frozen_position_is_not_playing_forever(self):
        player, child, session = self.setup_player()
        with patch("pi_player.mpv_player.read_reply", side_effect=[
                {"error": "success", "data": 1.0},
                {"error": "success", "data": 2.0},
                {"error": "success", "data": 2.0},
                {"error": "success", "data": 2.0}]), \
             patch("pi_player.mpv_player.time.monotonic", side_effect=[10, 11, 12, 72]):
            self.assertEqual(player.status(session)["state"], "starting")
            self.assertEqual(player.status(session)["state"], "playing")
            self.assertEqual(player.status(session)["state"], "playing")
            self.assertEqual(player.status(session)["state"], "stalled")
        self.assertTrue(player.stop(session))

    def test_invalid_positions_are_not_progress(self):
        player, child, session = self.setup_player()
        for value in (-1, float("nan"), float("inf"), 10**10000, True):
            with patch("pi_player.mpv_player.read_reply", return_value={"error": "success", "data": value}):
                result = player.status(session)
                self.assertEqual(result["state"], "starting")
                self.assertIsNone(result["position_seconds"])
                self.assertIn("monitor_error", result)
        self.assertTrue(player.stop(session))


    def test_invalid_sample_cannot_revive_stalled_playback(self):
        player, child, session = self.setup_player()
        samples = [1.0, 2.0, 2.0, float("inf"), 2.0]
        with patch("pi_player.mpv_player.read_reply",
                   side_effect=[{"error": "success", "data": n} for n in samples]), \
             patch("pi_player.mpv_player.time.monotonic", side_effect=[1, 2, 20, 21, 22]):
            states = [player.status(session) for _ in samples]
        self.assertEqual([r["state"] for r in states],
                         ["starting", "playing", "stalled", "stalled", "stalled"])
        self.assertIsNone(states[3]["position_seconds"])
        self.assertIn("monitor_error", states[3])
        self.assertEqual(player._last_position, 2.0)
        self.assertTrue(player.stop(session))

    def test_rejected_negative_sample_preserves_progress_baseline(self):
        player, child, session = self.setup_player()
        samples = [3.0, -1.0, 3.0, 3.06]
        with patch("pi_player.mpv_player.read_reply",
                   side_effect=[{"error": "success", "data": n} for n in samples]), \
             patch("pi_player.mpv_player.time.monotonic", side_effect=[1, 2, 3, 4]):
            states = [player.status(session) for _ in samples]
        self.assertEqual([r["state"] for r in states],
                         ["starting", "starting", "starting", "playing"])
        self.assertIsNone(states[1]["position_seconds"])
        self.assertTrue(player.stop(session))

    def test_small_cumulative_position_advances_count(self):
        player, child, session = self.setup_player()
        samples = [1.0, 1.04, 1.08, 1.12, 1.16]
        with patch("pi_player.mpv_player.read_reply",
                   side_effect=[{"error": "success", "data": n} for n in samples]), \
             patch("pi_player.mpv_player.time.monotonic", side_effect=[1, 2, 3, 4, 5]):
            states = [player.status(session)["state"] for _ in samples]
        self.assertEqual(states, ["starting", "starting", "playing", "playing", "playing"])
        self.assertTrue(player.stop(session))

    def test_exited_session_retires_socket(self):
        player, child, session = self.setup_player()
        old_dir = Path(player._ipc_dir.name)
        self.assertTrue(old_dir.exists())
        child.returncode = 0
        self.assertEqual(player.status(session)["state"], "exited")
        self.assertFalse(old_dir.exists())

    def test_invalid_stop_timeout_rejected(self):
        player, child, session = self.setup_player()
        for value in (float("nan"), float("inf"), -1, 0, 100, True, 10**10000):
            with self.assertRaises(ValueError):
                player.stop(session, timeout=value)
        self.assertTrue(player.stop(session))

    def test_failed_launch_cleans_temporary_directory(self):
        player = MpvPlayer(asset_dir=self.assets)
        if os.getuid() == 0:
            self.skipTest("launch test requires non-root Unix directory ownership")
        with patch("pi_player.mpv_player.os.geteuid", return_value=os.getuid()), \
             patch.dict(os.environ, {"XDG_RUNTIME_DIR": str(self.root)}), \
             patch("pi_player.mpv_player.subprocess.Popen", side_effect=OSError("launch failed")) as spawn:
            with self.assertRaisesRegex(OSError, "launch failed"):
                player.start(self.video)
        spawn.assert_called_once()
        self.assertEqual(list(self.root.glob("pi-player-mpv-*")), [])


@unittest.skipUnless(hasattr(socket, "AF_UNIX"), "Unix IPC required")
class IpcTests(unittest.TestCase):
    def test_events_and_fragmented_reply(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "ipc.sock"
            ready = threading.Event()
            def serve():
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
                    server.bind(str(path))
                    server.listen(1)
                    ready.set()
                    conn, _ = server.accept()
                    with conn:
                        conn.recv(4096)
                        conn.sendall(b'{"event":"start-file"}\n')
                        conn.sendall(b'{"request_id":1,"error":"success",')
                        time.sleep(0.01)
                        conn.sendall(b'"data":3.5}\n')
            thread = threading.Thread(target=serve, daemon=True)
            thread.start()
            self.assertTrue(ready.wait(2))
            reply = read_reply(path, ["get_property", "time-pos"])
            self.assertEqual(reply["data"], 3.5)
            thread.join(2)

    def test_invalid_non_object_reply(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "ipc.sock"
            ready = threading.Event()
            def serve():
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
                    server.bind(str(path))
                    server.listen(1)
                    ready.set()
                    conn, _ = server.accept()
                    with conn:
                        conn.recv(4096)
                        conn.sendall(b'42\n')
            thread = threading.Thread(target=serve, daemon=True)
            thread.start()
            self.assertTrue(ready.wait(2))
            with self.assertRaises(OSError):
                read_reply(path, ["get_property", "time-pos"])
            thread.join(2)


if __name__ == "__main__":
    unittest.main()

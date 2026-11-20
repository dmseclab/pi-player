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
        uid = os.getuid() or 1001
        # Tests run with a temporary directory owned by the real UID;
        # when root, simulate a non-root runtime directory owner.
        with patch("pi_player.mpv_player.os.geteuid", return_value=uid), \
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
        self.assertTrue(player.stop(session))

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

    def test_failed_launch_cleans_temporary_directory(self):
        player = MpvPlayer(asset_dir=self.assets)
        with patch("pi_player.mpv_player.os.geteuid", return_value=os.getuid() or 1001), \
             patch.dict(os.environ, {"XDG_RUNTIME_DIR": str(self.root)}), \
             patch("pi_player.mpv_player.subprocess.Popen", side_effect=OSError("launch failed")):
            with self.assertRaises(OSError):
                player.start(self.video)
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

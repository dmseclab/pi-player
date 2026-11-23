"""Opt-in broker daemon preflight; no listener is started."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pi_player.mpv_broker_service import validate_runtime_directory, run


class BrokerDaemonTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.private = self.root / "private"
        self.private.mkdir(mode=0o700)

    def test_private_runtime_directory_passes(self):
        validate_runtime_directory(self.private, kiosk_gid=os.getgid())

    def test_group_traverse_only_mode_permitted(self):
        self.private.chmod(0o710)
        validate_runtime_directory(self.private, kiosk_gid=os.getgid())

    def test_wrong_runtime_group_denied(self):
        self.private.chmod(0o710)
        with self.assertRaises(RuntimeError):
            validate_runtime_directory(self.private, kiosk_gid=os.getgid()+1)

    def test_world_accessible_runtime_directory_denied(self):
        self.private.chmod(0o755)
        with self.assertRaises(RuntimeError):
            validate_runtime_directory(self.private)

    def test_symlink_runtime_directory_denied(self):
        link = self.root / "link"
        link.symlink_to(self.private, target_is_directory=True)
        with self.assertRaises(RuntimeError):
            validate_runtime_directory(link, kiosk_gid=os.getgid())

    def test_shared_service_identities_block_start(self):
        with patch("pi_player.mpv_broker_service.identity", side_effect=[1001, 1001]), \
             patch("pi_player.mpv_broker_service.os.geteuid", return_value=1003):
            with self.assertRaises(RuntimeError):
                run(directory=self.private, database=self.root / "db.sqlite",
                    asset_root=self.root, api_user="api", kiosk_user="kiosk")


if __name__ == "__main__":
    unittest.main()

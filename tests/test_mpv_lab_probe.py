"""Offline tests for the non-mutating laboratory host probe."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pi_player.mpv_lab_probe import _unit_user, inspect


class LabProbeTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.api = self.root / "api.service"
        self.kiosk = self.root / "kiosk.service"
        self.controllers = self.root / "cgroup.controllers"
        self.controllers.write_text("cpu memory io\n")
        self.api.write_text("[Unit]\nDescription=API\n[Service]\nUser=pi-api\n")
        self.kiosk.write_text("[Service]\nUser=pi-kiosk\n")
        self.socketdir = self.root / "runtime"
        self.socketdir.mkdir()

    def inspect_report(self):
        return inspect(api_unit=self.api, kiosk_unit=self.kiosk,
                       cgroup_controllers=self.controllers,
                       compositor_socket_dir=self.socketdir)

    def test_user_declaration_only_from_service_section(self):
        self.assertEqual(_unit_user("[Unit]\nUser=root\n[Service]\nUser=pi\n"), "pi")
        self.assertIsNone(_unit_user("[Unit]\nUser=root\n"))

    def test_same_service_account_blocks(self):
        self.kiosk.write_text("[Service]\nUser=pi-api\n")
        report = self.inspect_report()
        self.assertIn("account_separation", report["blockers"])
        self.assertFalse(report["hybrid_activation_supported"])

    def test_missing_cgroup_blocks(self):
        self.controllers.unlink()
        self.assertIn("cgroup_v2", self.inspect_report()["blockers"])

    def test_no_wayland_socket_fails_closed(self):
        self.assertIn("wayland_socket", self.inspect_report()["blockers"])

    def test_missing_service_unit_fails_closed(self):
        self.api.unlink()
        report = self.inspect_report()
        self.assertIsNone(report["api_declared_account"])
        self.assertIn("account_separation", report["blockers"])

    def test_probe_has_no_activation_result(self):
        report = self.inspect_report()
        self.assertTrue(report["read_only"])
        self.assertFalse(report["hybrid_activation_supported"])


if __name__ == "__main__":
    unittest.main()

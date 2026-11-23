"""Reversible MPV lab service staging; never calls real systemctl."""
import importlib.util
import json
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock

FILE = Path(__file__).resolve().parents[1] / "deploy" / "stage-mpv-lab.py"
spec = importlib.util.spec_from_file_location("mpv_lab_staging", FILE)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class StageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.source = root / "source.service"
        self.source.write_text("[Service]\nUser=pi-player-broker\n")
        self.target = root / mod.UNIT_NAME
        self.state = root / "stage"
        self.runner = Mock(return_value=types.SimpleNamespace(returncode=1))

    def test_default_plan_never_changes_state(self):
        report = mod.planned(self.source, self.target, self.state)
        self.assertFalse(report["will_enable"])
        self.assertFalse(report["will_start"])
        self.assertFalse(self.target.exists())

    def test_stage_and_rollback_roundtrip(self):
        mod.stage(self.source, self.target, self.state, hostname="pi-player",
                  effective_uid=0, run=self.runner)
        self.assertTrue(self.target.exists())
        self.assertTrue((self.state / "manifest.json").exists())
        mod.rollback(self.target, self.state, hostname="pi-player",
                     effective_uid=0, run=self.runner)
        self.assertFalse(self.target.exists())
        self.assertFalse(self.state.exists())

    def test_construction_hostname_rejected(self):
        with self.assertRaises(RuntimeError):
            mod.stage(self.source, self.target, self.state,
                      hostname="pi-player-construction", effective_uid=0,
                      run=self.runner)
        self.assertFalse(self.target.exists())

    def test_nonroot_rejected(self):
        with self.assertRaises(RuntimeError):
            mod.stage(self.source, self.target, self.state,
                      hostname="pi-player", effective_uid=1000, run=self.runner)

    def test_existing_unit_never_overwritten(self):
        self.target.write_text("existing")
        with self.assertRaises(RuntimeError):
            mod.stage(self.source, self.target, self.state,
                      hostname="pi-player", effective_uid=0, run=self.runner)
        self.assertEqual(self.target.read_text(), "existing")

    def test_modified_unit_blocks_rollback(self):
        mod.stage(self.source, self.target, self.state, hostname="pi-player",
                  effective_uid=0, run=self.runner)
        self.target.write_text("changed")
        with self.assertRaises(RuntimeError):
            mod.rollback(self.target, self.state, hostname="pi-player",
                         effective_uid=0, run=self.runner)
        self.assertTrue(self.target.exists())

    def test_running_unit_blocks_rollback(self):
        mod.stage(self.source, self.target, self.state, hostname="pi-player",
                  effective_uid=0, run=self.runner)
        self.runner.return_value.returncode = 0
        with self.assertRaises(RuntimeError):
            mod.rollback(self.target, self.state, hostname="pi-player",
                         effective_uid=0, run=self.runner)
        self.assertTrue(self.target.exists())


if __name__ == "__main__":
    unittest.main()

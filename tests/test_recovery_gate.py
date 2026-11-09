"""Shared watchdog recovery gate; no pytest dependency."""
import importlib.util
import unittest
import tempfile
import json
from unittest.mock import patch
from pathlib import Path

path = Path(__file__).resolve().parents[1] / "deploy" / "pi-player-recovery-gate.py"
spec = importlib.util.spec_from_file_location("recovery_gate", path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class RecoveryGateTests(unittest.TestCase):
    def test_first_recovery_authorized(self):
        ok, state, _ = module.allowed({}, "kiosk", 100000, False)
        self.assertTrue(ok)
        self.assertEqual(state["history"]["kiosk"], [100000])

    def test_repeated_recovery_blocked_by_shared_cooldown(self):
        ok, state, _ = module.allowed({}, "kiosk", 100000, False)
        self.assertTrue(ok)
        ok, _, _ = module.allowed(state, "api", 100060, False)
        self.assertFalse(ok)
        ok, _, _ = module.allowed(state, "kiosk", 100060, False)
        self.assertFalse(ok)

    def test_blocked_kernel_tasks_prevent_recovery(self):
        ok, _, _ = module.allowed({}, "api", 100000, True)
        self.assertFalse(ok)

    def test_three_per_day_limit(self):
        state = {}
        for t in (100000, 100000 + 1200, 100000 + 2400):
            ok, state, _ = module.allowed(state, "kiosk", t, False)
            self.assertTrue(ok)
        ok, _, _ = module.allowed(state, "kiosk", 100000 + 3600, False)
        self.assertFalse(ok)

    def test_recovery_permitted_after_24h(self):
        state = {"history": {"kiosk": [100000, 101200, 102400]}}
        ok, _, _ = module.allowed(state, "kiosk", 100000 + 86401, False)
        self.assertTrue(ok)

    def test_malformed_histories_rejected(self):
        for invalid in (
            [], {"history": []}, {"history": {"kiosk": "100000"}},
            {"history": {"kiosk": [True]}}, {"history": {"kiosk": ["100000"]}},
            {"history": {"unknown": [100000]}}, {"history": {"kiosk": [-1]}}
        ):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    module.allowed(invalid, "kiosk", 100100, False)

    def test_corrupt_existing_state_denied_without_overwrite(self):
        with tempfile.TemporaryDirectory() as tempdir:
            state_path = Path(tempdir) / "gate.json"
            state_path.write_text('{"history": {"kiosk": "broken"}}')
            original = state_path.read_bytes()
            with patch.object(module, "STATE", state_path), patch.object(module, "blocked_tasks", return_value=False):
                self.assertEqual(module.main("kiosk"), 1)
            self.assertEqual(state_path.read_bytes(), original)

    def test_unreadable_state_denied(self):
        with tempfile.TemporaryDirectory() as tempdir:
            state_path = Path(tempdir) / "gate.json"
            state_path.mkdir()
            with patch.object(module, "STATE", state_path), patch.object(module, "blocked_tasks", return_value=False):
                self.assertEqual(module.main("kiosk"), 1)

    def test_valid_state_persisted(self):
        with tempfile.TemporaryDirectory() as tempdir:
            state_path = Path(tempdir) / "gate.json"
            with patch.object(module, "STATE", state_path), patch.object(module, "blocked_tasks", return_value=False):
                self.assertEqual(module.main("kiosk"), 0)
            recorded = json.loads(state_path.read_text())
            self.assertEqual(len(recorded["history"]["kiosk"]), 1)

    def test_invalid_kind_denied(self):
        ok, _, _ = module.allowed({}, "reboot", 100000, False)
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()

"""Shared watchdog recovery gate; no pytest dependency."""
import importlib.util
import unittest
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

    def test_invalid_kind_denied(self):
        ok, _, _ = module.allowed({}, "reboot", 100000, False)
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()

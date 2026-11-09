"""Dependency-free regression tests for advisory GPU resource monitoring."""
import importlib.util
import unittest
from pathlib import Path

MODULE = Path(__file__).resolve().parents[1] / "deploy" / "pi-player-gpu-watchdog.py"
spec = importlib.util.spec_from_file_location("gpu_watchdog", MODULE)
watchdog = importlib.util.module_from_spec(spec)
spec.loader.exec_module(watchdog)
HIGH = [{"pid": 123, "fds": 1300, "chromium_shm": 1250}]
LOW = [{"pid": 123, "fds": 70, "chromium_shm": 25}]


class GpuWatchdogTests(unittest.TestCase):
    def test_three_high_samples_request_recovery(self):
        state = {}
        for n in range(1, 4):
            state, request = watchdog.next_state(state, HIGH, [], 10000 + n * 60, "boot1")
            self.assertEqual(request, n == 3)
        self.assertEqual(state["high_samples"], 3)

    def test_denied_recovery_does_not_consume_attempt(self):
        state = {}
        for n in range(4):
            state, request = watchdog.next_state(state, HIGH, [], 10000 + n * 60, "boot1")
        self.assertTrue(request)
        self.assertEqual(state, {"boot_id": "boot1", "high_samples": 3})
        self.assertNotIn("recoveries", state)

    def test_low_sample_resets_counter(self):
        state, _ = watchdog.next_state({}, HIGH, [], 10000, "boot1")
        state, request = watchdog.next_state(state, LOW, [], 10060, "boot1")
        self.assertFalse(request)
        self.assertEqual(state["high_samples"], 0)

    def test_blocked_tasks_prevent_request(self):
        state = {}
        for n in range(4):
            state, request = watchdog.next_state(state, HIGH, [88], 10000 + n * 60, "boot1")
            self.assertFalse(request)
        self.assertEqual(state["high_samples"], 3)

    def test_new_boot_resets_samples(self):
        state, _ = watchdog.next_state({}, HIGH, [], 10000, "boot1")
        state, request = watchdog.next_state(state, HIGH, [], 10060, "boot2")
        self.assertFalse(request)
        self.assertEqual(state["high_samples"], 1)

    def test_invalid_counter_fails_closed(self):
        with self.assertRaises(ValueError):
            watchdog.next_state({"boot_id": "boot1", "high_samples": "3"}, HIGH, [], 10000, "boot1")


if __name__ == "__main__":
    unittest.main()

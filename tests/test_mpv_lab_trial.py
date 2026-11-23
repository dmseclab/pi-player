"""Offline preflight tests for lab-only opt-in; no subprocess runs."""
import unittest
from pathlib import Path
from unittest.mock import patch

from pi_player.mpv_lab_trial import preflight, run_trial


class LabTrialTests(unittest.TestCase):
    def test_preflight_requires_explicit_opt_in(self):
        errors = preflight(hostname="pi-player", is_root=False,
                           hybrid_ack=False, wayland_display="wayland-0",
                           runtime="/run/user/1000",
                           broker_socket=Path("/nonexistent/media.sock"))
        self.assertIn("no-manual-lab-approval", errors)
        self.assertIn("broker-socket-unavailable", errors)

    def test_production_hostname_denied(self):
        errors = preflight(hostname="pi-player-construction", is_root=False,
                           hybrid_ack=True, wayland_display="wayland-0",
                           runtime="/run/user/1000",
                           broker_socket=Path("/nonexistent"))
        self.assertIn("lab-hostname", errors)

    def test_root_user_denied(self):
        errors = preflight(hostname="pi-player", is_root=True,
                           hybrid_ack=True, wayland_display="wayland-0",
                           runtime="/run/user/1000",
                           broker_socket=Path("/nonexistent"))
        self.assertIn("root-user", errors)

    def test_invalid_duration_denied_before_socket(self):
        for seconds in (0, 121):
            with self.subTest(seconds=seconds), self.assertRaises(ValueError):
                run_trial(item_id="00000000-0000-0000-0000-000000000001",
                          broker_socket=Path("/nonexistent"),
                          broker_user="broker", seconds=seconds)

    def test_invalid_item_identity_denied_before_socket(self):
        with self.assertRaises(ValueError):
            run_trial(item_id="not-uuid", broker_socket=Path("/nonexistent"),
                      broker_user="broker", seconds=10)


if __name__ == "__main__":
    unittest.main()

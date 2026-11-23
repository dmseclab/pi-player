"""No GUI interaction: fake the wlrctl subprocess and test fallback."""
import subprocess
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import Mock

from pi_player.mpv_handover import OfflineHandover, SurfaceWitness
from pi_player.mpv_wayland_switch import (
    WlrctlFocus, WaylandHandoverActuator, WaylandSwitchError,
)


class WaylandFocusTests(unittest.TestCase):
    def setUp(self):
        self.gate = OfflineHandover()
        self.slot, self.child, self.entry = (str(uuid.uuid4()) for _ in range(3))
        self.gate.begin(self.slot, self.child, self.entry)
        self.mpv_id = "pi-player-mpv-" + "a"*32
        self.calls = []
        self.active = self.mpv_id
        def runner(args, **kwargs):
            self.calls.append(args)
            if args[2] == "list":
                return SimpleNamespace(stdout=self.active + ": test\n")
            return SimpleNamespace(stdout="")
        self.runner = runner
        self.focus = WlrctlFocus(runner=self.runner)
        self.actuator = WaylandHandoverActuator(
            self.gate, self.focus, chromium_app_id="chromium")

    def prepare(self):
        self.gate.note_surface(SurfaceWitness(self.slot, self.child,
                                             "observed", True))
        self.gate.note_progress(self.slot, self.child, self.entry, advanced=True)

    def test_does_not_focus_before_both_evidences(self):
        self.assertFalse(self.actuator.to_mpv(
            self.slot, self.child, self.entry, mpv_app_id=self.mpv_id))
        self.assertFalse(self.calls)

    def test_focus_with_exact_readback_commits(self):
        self.prepare()
        self.assertTrue(self.actuator.to_mpv(
            self.slot, self.child, self.entry, mpv_app_id=self.mpv_id))
        self.assertEqual(self.gate.snapshot()["display_owner"], "mpv")

    def test_failed_readback_attempts_chromium_restore(self):
        self.prepare()
        self.active = "chromium"
        self.assertFalse(self.actuator.to_mpv(
            self.slot, self.child, self.entry, mpv_app_id=self.mpv_id))
        self.assertEqual(self.gate.snapshot()["display_owner"], "chromium")
        self.assertTrue(any("app_id:chromium" in args for args in self.calls))

    def test_invalid_app_id_rejected_without_focus(self):
        self.prepare()
        with self.assertRaises(WaylandSwitchError):
            self.actuator.to_mpv(self.slot, self.child, self.entry,
                                 mpv_app_id="bad;command")
        self.assertFalse(self.calls)

    def test_restore_failure_does_not_claim_visual_success(self):
        self.prepare()
        self.active = "wrong"
        self.assertFalse(self.actuator.restore_chromium())
        self.assertEqual(self.gate.snapshot()["display_owner"], "chromium")


if __name__ == "__main__":
    unittest.main()

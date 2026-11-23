import unittest
import uuid
from pi_player.mpv_handover import (
    OfflineHandover, HandoverError, SurfaceWitness,
)


def uid():
    return str(uuid.uuid4())


class HandoverTests(unittest.TestCase):
    def setUp(self):
        self.gate = OfflineHandover()
        self.slot, self.child, self.entry = uid(), uid(), uid()
        self.gate.begin(self.slot, self.child, self.entry)

    def test_chromium_stays_owner_without_both_evidences(self):
        self.assertFalse(self.gate.ready(self.slot, self.child, self.entry))
        self.gate.note_progress(self.slot, self.child, self.entry, advanced=True)
        self.assertFalse(self.gate.ready(self.slot, self.child, self.entry))
        self.assertEqual(self.gate.snapshot()["display_owner"], "chromium")

    def test_trusted_progress_and_surface_allow_handover(self):
        self.gate.note_surface(SurfaceWitness(self.slot, self.child, "wl-77", True))
        self.assertFalse(self.gate.ready(self.slot, self.child, self.entry))
        self.gate.note_progress(self.slot, self.child, self.entry, advanced=True)
        self.assertTrue(self.gate.ready(self.slot, self.child, self.entry))
        self.gate.commit_visible(self.slot, self.child, self.entry)
        self.assertEqual(self.gate.snapshot()["display_owner"], "mpv")

    def test_wrong_child_surface_cannot_authorize(self):
        with self.assertRaises(HandoverError):
            self.gate.note_surface(SurfaceWitness(self.slot, uid(), "wl-88", True))
        self.assertFalse(self.gate.snapshot()["surface_ready"])

    def test_stale_entry_progress_rejected(self):
        with self.assertRaises(HandoverError):
            self.gate.note_progress(self.slot, self.child, uid(), advanced=True)

    def test_takeover_cannot_repeat_without_rollback(self):
        self.gate.note_surface(SurfaceWitness(self.slot, self.child, "wl-77", True))
        self.gate.note_progress(self.slot, self.child, self.entry, advanced=True)
        self.gate.commit_visible(self.slot, self.child, self.entry)
        with self.assertRaises(HandoverError):
            self.gate.begin(uid(), uid(), uid())
        self.gate.rollback()
        self.assertEqual(self.gate.snapshot()["display_owner"], "chromium")
        self.gate.begin(uid(), uid(), uid())

    def test_rollback_revokes_stale_readiness(self):
        self.gate.note_surface(SurfaceWitness(self.slot, self.child, "wl-77", True))
        self.gate.note_progress(self.slot, self.child, self.entry, advanced=True)
        self.gate.rollback()
        self.assertFalse(self.gate.ready(self.slot, self.child, self.entry))
        self.assertEqual(self.gate.snapshot()["display_owner"], "chromium")

    def test_second_pending_handover_denied(self):
        with self.assertRaises(HandoverError):
            self.gate.begin(uid(), uid(), uid())


if __name__ == "__main__":
    unittest.main()

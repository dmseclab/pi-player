"""Deterministic retirement interlock tests. No child processes spawned."""
import unittest
import uuid

from pi_player.mpv_owner import OfflineOwner
from pi_player.mpv_process_evidence import GroupEvidence, EvidenceError
from pi_player.mpv_retirement import OfflineProcessRetirement, RetirementError


class RetirementTests(unittest.TestCase):
    def setUp(self):
        self.owner = OfflineOwner()
        self.owner.reconcile_empty()
        self.lease = self.owner.replace_owner(str(uuid.uuid4()))
        self.slot = self.owner.reserve(self.lease)
        self.child = str(uuid.uuid4())
        self.evidence = GroupEvidence(True, 0, ())
        self.retirement = OfflineProcessRetirement(
            self.owner, lambda: self.evidence)
        self.retirement.bind_child(self.lease, self.slot, self.child, 777)

    def test_requires_exact_exit_and_launcher_close(self):
        with self.assertRaises(RetirementError):
            self.retirement.retire(self.child)
        self.retirement.witnessed_exit(self.child, 777)
        with self.assertRaises(RetirementError):
            self.retirement.retire(self.child)
        self.retirement.launcher_quiescent(self.child)
        self.retirement.retire(self.child)
        self.assertEqual(self.owner.snapshot()["slot_state"], "empty")

    def test_incorrect_pid_is_not_exit(self):
        with self.assertRaises(RetirementError):
            self.retirement.witnessed_exit(self.child, 778)
        self.assertFalse(self.retirement.snapshot()["exit_witnessed"])

    def test_wrong_child_cannot_retire(self):
        with self.assertRaises(RetirementError):
            self.retirement.retire(str(uuid.uuid4()))

    def test_populated_group_retains_renderer(self):
        self.retirement.witnessed_exit(self.child, 777)
        self.retirement.launcher_quiescent(self.child)
        self.evidence = GroupEvidence(False, 1, (778,))
        with self.assertRaises(RetirementError):
            self.retirement.retire(self.child)
        self.assertEqual(self.owner.snapshot()["slot_state"], "running")

    def test_unavailable_inspector_retains_renderer(self):
        self.retirement.witnessed_exit(self.child, 777)
        self.retirement.launcher_quiescent(self.child)
        self.retirement.evidence = lambda: (_ for _ in ()).throw(EvidenceError("missing"))
        with self.assertRaises(RetirementError):
            self.retirement.retire(self.child)
        self.assertEqual(self.owner.snapshot()["slot_state"], "running")

    def test_duplicate_process_registration_denied(self):
        with self.assertRaises(RetirementError):
            self.retirement.bind_child(self.lease, self.slot, str(uuid.uuid4()), 778)

    def test_replaced_owner_does_not_release_quarantined_slot_without_evidence(self):
        self.owner.replace_owner(str(uuid.uuid4()))
        self.retirement.witnessed_exit(self.child, 777)
        self.retirement.launcher_quiescent(self.child)
        self.evidence = GroupEvidence(False, 1, (999,))
        with self.assertRaises(RetirementError):
            self.retirement.retire(self.child)
        self.assertEqual(self.owner.snapshot()["slot_state"], "quarantined")
        self.evidence = GroupEvidence(True, 0, ())
        self.retirement.retire(self.child)
        self.assertEqual(self.owner.snapshot()["slot_state"], "empty")


if __name__ == "__main__":
    unittest.main()

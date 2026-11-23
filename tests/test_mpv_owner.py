"""Phase 2B-1 offline lease and renderer safety checks; no Pi or processes."""
import threading
import unittest
import uuid

from pi_player.mpv_owner import OfflineOwner, OwnerError, OwnerLease


def ident():
    return str(uuid.uuid4())


class OwnerPolicyTests(unittest.TestCase):
    def setUp(self):
        self.owner = OfflineOwner()
        self.lease = self.owner.replace_owner(ident())

    def test_startup_requires_explicit_reconciliation(self):
        with self.assertRaises(OwnerError):
            self.owner.reserve(self.lease)
        self.owner.reconcile_empty()
        self.assertTrue(self.owner.snapshot()["reconciled"])
        self.assertTrue(self.owner.reserve(self.lease))

    def test_epoch_is_fresh_even_for_same_owner(self):
        self.owner.reconcile_empty()
        previous = self.lease
        current = self.owner.replace_owner(previous.owner_id)
        self.assertNotEqual(previous.epoch, current.epoch)
        with self.assertRaises(OwnerError):
            self.owner.reserve(previous)
        self.assertTrue(self.owner.reserve(current))

    def test_epoch_is_not_returned_by_snapshot(self):
        self.owner.reconcile_empty()
        snapshot = self.owner.snapshot()
        self.assertNotIn(self.lease.epoch, str(snapshot))
        self.assertNotIn("child_id", snapshot)

    def test_replacement_quarantines_reserved_slot(self):
        self.owner.reconcile_empty()
        slot = self.owner.reserve(self.lease)
        new = self.owner.replace_owner(ident())
        self.assertEqual(self.owner.snapshot()["slot_state"], "quarantined")
        with self.assertRaises(OwnerError):
            self.owner.reserve(new)
        with self.assertRaises(OwnerError):
            self.owner.mark_spawned(self.lease, slot, ident())
        self.owner.cancel_unspawned(slot, launch_ruled_out=True)
        self.assertTrue(self.owner.reserve(new))

    def test_replacement_quarantines_running_child(self):
        self.owner.reconcile_empty()
        slot = self.owner.reserve(self.lease)
        child = ident()
        self.owner.mark_spawned(self.lease, slot, child)
        next_owner = self.owner.replace_owner(ident())
        with self.assertRaises(OwnerError):
            self.owner.reserve(next_owner)
        with self.assertRaises(OwnerError):
            self.owner.cancel_unspawned(slot, launch_ruled_out=True)
        self.owner.confirm_exit(slot, child, group_empty=True)
        self.assertTrue(self.owner.reserve(next_owner))

    def test_stale_exit_cannot_clear_new_slot(self):
        self.owner.reconcile_empty()
        first = self.owner.reserve(self.lease)
        first_child = ident()
        self.owner.mark_spawned(self.lease, first, first_child)
        self.owner.confirm_exit(first, first_child, group_empty=True)
        second = self.owner.reserve(self.lease)
        second_child = ident()
        self.owner.mark_spawned(self.lease, second, second_child)
        with self.assertRaises(OwnerError):
            self.owner.confirm_exit(first, first_child, group_empty=True)
        self.assertEqual(self.owner.snapshot()["slot_id"], second)

    def test_wrong_child_and_nonempty_group_do_not_release(self):
        self.owner.reconcile_empty()
        slot = self.owner.reserve(self.lease)
        child = ident()
        self.owner.mark_spawned(self.lease, slot, child)
        for other, empty in ((ident(), True), (child, False), (child, 1)):
            with self.subTest(other=other, empty=empty), self.assertRaises(OwnerError):
                self.owner.confirm_exit(slot, other, group_empty=empty)
        self.assertEqual(self.owner.snapshot()["slot_state"], "running")

    def test_quarantine_on_loss_retains_slot(self):
        self.owner.reconcile_empty()
        slot = self.owner.reserve(self.lease)
        child = ident()
        self.owner.mark_spawned(self.lease, slot, child)
        self.owner.quarantine(slot)
        with self.assertRaises(OwnerError):
            self.owner.reserve(self.lease)
        self.owner.confirm_exit(slot, child, group_empty=True)
        self.assertEqual(self.owner.snapshot()["slot_state"], "empty")

    def test_reserved_cleanup_requires_proof(self):
        self.owner.reconcile_empty()
        slot = self.owner.reserve(self.lease)
        for proof in (False, 1, None):
            with self.subTest(proof=proof), self.assertRaises(OwnerError):
                self.owner.cancel_unspawned(slot, launch_ruled_out=proof)
        with self.assertRaises(OwnerError):
            self.owner.reconcile_empty()
        self.owner.cancel_unspawned(slot, launch_ruled_out=True)
        self.owner.reconcile_empty()

    def test_revoke_fences_owner_and_keeps_renderer(self):
        self.owner.reconcile_empty()
        slot = self.owner.reserve(self.lease)
        self.owner.revoke_owner(self.lease)
        with self.assertRaises(OwnerError):
            self.owner.reserve(self.lease)
        self.assertEqual(self.owner.snapshot()["slot_state"], "quarantined")
        self.owner.cancel_unspawned(slot, launch_ruled_out=True)

    def test_invalid_ids_are_rejected_without_mutation(self):
        self.owner.reconcile_empty()
        baseline = self.owner.snapshot()
        for value in ("bad", True, None, ident().upper()):
            with self.subTest(value=value), self.assertRaises(OwnerError):
                self.owner.replace_owner(value)
        self.assertEqual(self.owner.snapshot(), baseline)
        with self.assertRaises(OwnerError):
            self.owner.reserve(OwnerLease(self.lease.owner_id, "wrong"))
        self.assertEqual(self.owner.snapshot(), baseline)

    def test_parallel_reservations_one_winner(self):
        self.owner.reconcile_empty()
        barrier = threading.Barrier(3)
        results = []
        guard = threading.Lock()
        def attempt():
            barrier.wait()
            try:
                self.owner.reserve(self.lease)
                value = "ok"
            except OwnerError:
                value = "denied"
            with guard:
                results.append(value)
        threads = [threading.Thread(target=attempt) for _ in range(2)]
        for thread in threads:
            thread.start()
        barrier.wait()
        for thread in threads:
            thread.join(timeout=3)
            self.assertFalse(thread.is_alive())
        self.assertEqual(sorted(results), ["denied", "ok"])

    def test_restart_is_unreconciled_and_old_epoch_rejected(self):
        self.owner.reconcile_empty()
        self.owner.reserve(self.lease)
        new_process = OfflineOwner()
        new_lease = new_process.replace_owner(self.lease.owner_id)
        self.assertNotEqual(new_lease.epoch, self.lease.epoch)
        with self.assertRaises(OwnerError):
            new_process.reserve(new_lease)
        with self.assertRaises(OwnerError):
            new_process.reserve(self.lease)

    def test_stale_owner_cannot_mutate_after_replacement(self):
        self.owner.reconcile_empty()
        slot = self.owner.reserve(self.lease)
        latest = self.owner.replace_owner(ident())
        with self.assertRaises(OwnerError):
            self.owner.mark_spawned(self.lease, slot, ident())
        with self.assertRaises(OwnerError):
            self.owner.revoke_owner(self.lease)
        self.assertEqual(self.owner.snapshot()["slot_state"], "quarantined")
        self.owner.cancel_unspawned(slot, launch_ruled_out=True)
        self.assertTrue(self.owner.reserve(latest))


if __name__ == "__main__":
    unittest.main()

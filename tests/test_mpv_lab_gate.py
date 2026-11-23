"""Phase 2B read-only lab safety checklist tests."""
import unittest
from pi_player.mpv_lab_gate import evaluate, readiness, inspect_source_units


class GateTests(unittest.TestCase):
    def facts(self):
        return {
            "api_uid": 1001, "kiosk_uid": 1002, "broker_uid": 1003,
            "service_api_uid": 1001, "service_kiosk_uid": 1002,
            "cgroup_v2": True, "wayland": True, "mpv_binary": True,
            "kernel_healthy": True, "production_freeze": True,
            "verified_restore_plan": True, "feature_enabled": False,
        }

    def test_all_evidence_required(self):
        self.assertTrue(readiness(self.facts()))
        self.assertEqual(len(evaluate(self.facts())), 8)

    def test_same_api_and_kiosk_account_blocks(self):
        facts = self.facts()
        facts["kiosk_uid"] = facts["api_uid"]
        self.assertFalse(readiness(facts))

    def test_broker_must_be_separate_account(self):
        facts = self.facts()
        facts["broker_uid"] = facts["api_uid"]
        self.assertFalse(readiness(facts))

    def test_source_service_identity_mismatch_blocks(self):
        facts = self.facts()
        facts["service_kiosk_uid"] = 9999
        self.assertFalse(readiness(facts))

    def test_missing_evidence_denied(self):
        facts = self.facts()
        del facts["kernel_healthy"]
        with self.assertRaises(ValueError):
            readiness(facts)

    def test_feature_enabled_blocks_preflight(self):
        facts = self.facts()
        facts["feature_enabled"] = True
        self.assertFalse(readiness(facts))

    def test_each_hardware_condition_blocks(self):
        for key in ("cgroup_v2", "wayland", "mpv_binary",
                    "kernel_healthy", "production_freeze",
                    "verified_restore_plan"):
            with self.subTest(key=key):
                facts = self.facts()
                facts[key] = False
                self.assertFalse(readiness(facts))

    def test_source_units_same_user_detected(self):
        gates = inspect_source_units("[Service]\nUser=pi\n",
                                     "[Service]\nUser=pi\n")
        self.assertFalse(gates[-1].passed)

    def test_source_units_distinct_users_accepted(self):
        gates = inspect_source_units("[Service]\nUser=pi-api\n",
                                     "[Service]\nUser=pi-kiosk\n")
        self.assertTrue(all(g.passed for g in gates))

    def test_undeclared_user_is_not_accepted(self):
        gates = inspect_source_units("[Service]\nExecStart=x\n",
                                     "[Service]\nUser=pi\n")
        self.assertFalse(gates[0].passed)
        self.assertFalse(gates[2].passed)


if __name__ == "__main__":
    unittest.main()

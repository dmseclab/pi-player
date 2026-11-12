import subprocess
import unittest
from unittest.mock import Mock, create_autospec

from pi_player.network_dhcp import HotspotDHCP
from pi_player.network_gate import Gate
from pi_player.network_gate_verify import expected_ruleset, matches_ruleset, verify_gate, NFT
from pi_player.network_guard import guard


class GateReadbackTests(unittest.TestCase):
    def test_exact_modes(self):
        for mode in Gate:
            rules = expected_ruleset(mode)
            self.assertTrue(matches_ruleset(mode, rules))
            for other in Gate:
                self.assertEqual(matches_ruleset(other, rules), other == mode)

    def test_only_formatting_ignored(self):
        rules = expected_ruleset(Gate.HOTSPOT)
        self.assertTrue(matches_ruleset(Gate.HOTSPOT, "\n\n".join(
            "\t" + line.strip() for line in rules.splitlines())))

    def test_missing_or_modified_chain_rejected(self):
        rules = expected_ruleset(Gate.WIRED)
        for altered in ("", rules.replace("policy drop;", "policy accept;", 1),
                        rules.replace('device "wlan0"', 'device "eth0"', 1),
                        rules.replace("priority -500;", "priority 0;", 1)):
            self.assertFalse(matches_ruleset(Gate.WIRED, altered))

    def test_missing_or_reordered_ap_rule_rejected(self):
        rules = expected_ruleset(Gate.HOTSPOT)
        self.assertFalse(matches_ruleset(Gate.HOTSPOT, rules.replace(
            '        iifname "wlan0" counter drop\n', "")))
        lines = rules.splitlines()
        a = next(i for i, line in enumerate(lines) if "tcp dport 18000" in line)
        lines[a], lines[a+1] = lines[a+1], lines[a]
        self.assertFalse(matches_ruleset(Gate.HOTSPOT, "\n".join(lines)))

    def test_extra_rule_or_foreign_table_rejected(self):
        rules = expected_ruleset(Gate.HOTSPOT)
        self.assertFalse(matches_ruleset(Gate.HOTSPOT, rules + "table ip foreign {\n}\n"))
        self.assertFalse(matches_ruleset(Gate.HOTSPOT, rules.replace(
            '        iifname "wlan0" counter drop',
            '        iifname "wlan0" tcp dport 8000 accept\n        iifname "wlan0" counter drop')))

    def test_readback_read_only(self):
        runner = Mock(return_value=subprocess.CompletedProcess([], 0, expected_ruleset(Gate.CLIENT), ""))
        self.assertTrue(verify_gate(Gate.CLIENT, runner))
        runner.assert_called_once()
        self.assertEqual(runner.call_args.args[0], [NFT, "-s", "-y", "list", "ruleset"])

    def test_unavailable_readback_fails_closed(self):
        for error in (OSError("not available"), subprocess.CalledProcessError(1, "nft"),
                      subprocess.TimeoutExpired("nft", 10)):
            self.assertFalse(verify_gate(Gate.HOTSPOT, Mock(side_effect=error)))


class DHCPGuardTests(unittest.TestCase):
    def test_requires_root(self):
        factory = create_autospec(HotspotDHCP)
        self.assertFalse(guard(uid=lambda: 1000, factory=factory))
        factory.assert_not_called()

    def test_passes_independent_verifier(self):
        factory = create_autospec(HotspotDHCP)
        verifier = Mock(return_value=True)
        self.assertTrue(guard(uid=lambda: 0, factory=factory, verifier=verifier))
        factory.assert_called_once_with(gate_verified=verifier)
        factory.return_value.assert_safe.assert_called_once_with()

    def test_guard_rejects_unsafe_or_unknown_state(self):
        factory = create_autospec(HotspotDHCP)
        factory.return_value.assert_safe.side_effect = RuntimeError("unsafe")
        self.assertFalse(guard(uid=lambda: 0, factory=factory))
        self.assertFalse(guard(uid=lambda: 0, factory=Mock(side_effect=OSError("unavailable"))))


if __name__ == "__main__":
    unittest.main()

import subprocess
import unittest
from unittest.mock import Mock

from pi_player.network_gate import Gate, render_gate, check_gate, replace_gate, render_hotspot_dhcp


class NetworkGateTests(unittest.TestCase):
    def assert_policy(self, rules, iface, direction, policy):
        fragment = rules.split(f"chain {iface}_{direction} {{", 1)[1].split("}", 1)[0]
        self.assertIn(f' hook {direction} device "{iface}" ', fragment)
        self.assertIn(f"policy {policy};", fragment)

    def test_gate_modes_are_exclusive(self):
        for mode, eth, wlan in (
            (Gate.CLOSED, "drop", "drop"),
            (Gate.WIRED, "accept", "drop"),
            (Gate.CLIENT, "drop", "accept"),
            (Gate.HOTSPOT, "accept", "accept"),
        ):
            rules = render_gate(mode)
            for direction in ("ingress", "egress"):
                self.assert_policy(rules, "eth0", direction, eth)
                self.assert_policy(rules, "wlan0", direction, wlan)
            self.assertIn('iifname { "eth0", "wlan0" } counter drop', rules)
            self.assertIn('oifname { "eth0", "wlan0" } counter drop', rules)
            self.assertNotIn("masquerade", rules)

    def test_hotspot_only_test_http_and_dhcp(self):
        rules = render_gate(Gate.HOTSPOT)
        self.assertIn("tcp dport 18000 counter accept", rules)
        self.assertNotIn("tcp dport 8000", rules)
        self.assertNotIn("tcp dport 22", rules)
        self.assertIn('iifname "wlan0" counter drop', rules)
        self.assertIn('oifname "wlan0" counter drop', rules)

    def test_check_does_not_apply(self):
        runner = Mock()
        check_gate(Gate.WIRED, runner)
        self.assertEqual(runner.call_count, 1)
        self.assertEqual(runner.call_args.args[0], ["/usr/sbin/nft", "-c", "-f", "-"])

    def test_replace_checks_first_and_uses_same_transaction(self):
        runner = Mock()
        replace_gate(Gate.CLIENT, runner)
        first, second = runner.call_args_list
        self.assertIn("-c", first.args[0])
        self.assertNotIn("-c", second.args[0])
        self.assertEqual(first.kwargs["input"], second.kwargs["input"])

    def test_failed_check_never_applies(self):
        runner = Mock(side_effect=subprocess.CalledProcessError(1, "nft"))
        with self.assertRaises(subprocess.CalledProcessError):
            replace_gate(Gate.CLIENT, runner)
        self.assertEqual(runner.call_count, 1)

    def test_invalid_mode_rejected(self):
        runner = Mock()
        with self.assertRaises(ValueError):
            replace_gate("unexpected", runner)
        runner.assert_not_called()

    def test_dhcp_is_hotspot_only(self):
        config = render_hotspot_dhcp()
        self.assertIn("interface=wlan0\n", config)
        self.assertNotIn("eth0", config)
        self.assertIn("dhcp-range=10.42.0.2,10.42.0.3,255.255.255.0,1h", config)
        self.assertIn("dhcp-lease-max=2", config)
        self.assertIn("dhcp-option=option:router\n", config)
        self.assertIn("dhcp-option=option:dns-server\n", config)


if __name__ == "__main__":
    unittest.main()

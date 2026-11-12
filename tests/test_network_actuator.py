import json
import subprocess
import unittest
from dataclasses import replace
from unittest.mock import Mock

from pi_player.network_actuator import (
    WiredActuator, WiredObservation, SafetyError, FALLBACK_UUID, FALLBACK_NAME,
    NM, IP, ETHERNET_FALLBACK,
)

PRIMARY = "7f938629-fbbc-4ea6-9b94-f59a16442188"


class WiredActuatorTests(unittest.TestCase):
    def setUp(self):
        self.a = WiredActuator()
        self.empty = WiredObservation(True, PRIMARY, (), False, True)
        self.fallback = WiredObservation(True, FALLBACK_UUID, (ETHERNET_FALLBACK,), False, True)
        self.a.observe = Mock(return_value=self.empty)
        self.a.routes = Mock(return_value=[])
        self.a.nm = Mock(return_value=PRIMARY)
        primary_fields = {
            "connection.type": "802-3-ethernet", "connection.interface-name": "eth0",
            "connection.autoconnect": "no", "ipv4.method": "auto", "ipv4.addresses": "",
        }
        fallback_fields = {
            "connection.id": FALLBACK_NAME, "connection.type": "802-3-ethernet",
            "connection.interface-name": "eth0", "connection.autoconnect": "no",
            "ipv4.method": "manual", "ipv4.addresses": ETHERNET_FALLBACK,
            "ipv4.never-default": "yes", "ipv4.may-fail": "no", "ipv4.dad-timeout": "3000",
            "ipv4.gateway": "", "ipv4.dns": "", "ipv6.method": "disabled",
        }
        self.a.field = Mock(side_effect=lambda profile, field:
                            (primary_fields if profile == PRIMARY else fallback_fields)[field])

    def test_read_only_observer(self):
        responses = {
            (NM, "-t", "-f", "UUID,DEVICE", "connection", "show", "--active"): PRIMARY + ":eth0",
            (IP, "-j", "-4", "address", "show", "dev", "eth0"): json.dumps([{"addr_info": [
                {"family": "inet", "scope": "global", "local": "192.0.2.10", "prefixlen": 24}]}]),
            (IP, "-j", "-4", "route", "show", "table", "all"): json.dumps([{"dst": "default", "dev": "eth0"}]),
            (NM, "radio", "wifi"): "disabled",
        }
        runner = Mock(side_effect=lambda args, **kwargs: subprocess.CompletedProcess(args, 0, responses[tuple(args)], ""))
        result = WiredActuator(runner=runner, carrier_reader=lambda: True).observe()
        self.assertEqual(result, WiredObservation(True, PRIMARY, ("192.0.2.10/24",), True, True))
        self.assertEqual(runner.call_count, 4)

    def test_requires_timeout_and_gate(self):
        for elapsed, gate in [(29, True), (30, False)]:
            with self.assertRaises(SafetyError):
                self.a.start_fallback(PRIMARY, elapsed=elapsed, verified_wired_gate=gate)
        self.a.nm.assert_not_called()

    def test_primary_must_be_owned_dhcp(self):
        self.a.field.side_effect = lambda profile, field: "manual" if field == "ipv4.method" else {
            "connection.type": "802-3-ethernet", "connection.interface-name": "eth0",
            "connection.autoconnect": "no"}[field]
        with self.assertRaises(SafetyError):
            self.a.start_fallback(PRIMARY, elapsed=30, verified_wired_gate=True)
        self.a.nm.assert_not_called()

    def test_no_override_of_live_or_foreign_connection(self):
        for obs in (replace(self.empty, ipv4_addresses=("192.0.2.10/24",)),
                    replace(self.empty, default_route=True),
                    replace(self.empty, carrier=None),
                    replace(self.empty, wifi_disabled=False),
                    replace(self.empty, active_uuid=FALLBACK_UUID)):
            self.a.observe.return_value = obs
            with self.assertRaises(SafetyError):
                self.a.start_fallback(PRIMARY, elapsed=30, verified_wired_gate=True)
        self.a.nm.assert_not_called()

    def test_route_conflict(self):
        self.a.routes.return_value = [{"dst": "10.42.0.0/16"}]
        with self.assertRaises(SafetyError):
            self.a.start_fallback(PRIMARY, elapsed=30, verified_wired_gate=True)
        self.a.nm.assert_not_called()

    def test_fallback_profile_collision(self):
        self.a.nm.return_value = FALLBACK_UUID
        with self.assertRaises(SafetyError):
            self.a.start_fallback(PRIMARY, elapsed=30, verified_wired_gate=True)
        self.assertEqual(self.a.nm.call_count, 1)

    def test_fallback_create_and_verify(self):
        self.a.observe.side_effect = [self.empty, self.empty, self.fallback]
        self.assertEqual(self.a.start_fallback(PRIMARY, elapsed=30, verified_wired_gate=True), self.fallback)
        calls = [call.args for call in self.a.nm.call_args_list]
        self.assertIn(("ipv4.dad-timeout", "3000"), list(zip(calls[1], calls[1][1:])))
        self.assertIn("save", calls[1])
        self.assertEqual(calls[-1], ("--wait", "30", "connection", "up", "uuid", FALLBACK_UUID, "ifname", "eth0"))

    def test_fallback_recheck_preserves_new_dhcp_address(self):
        self.a.observe.side_effect = [self.empty, replace(self.empty, ipv4_addresses=("192.0.2.10/24",))]
        with self.assertRaises(SafetyError):
            self.a.start_fallback(PRIMARY, elapsed=30, verified_wired_gate=True)
        self.a.nm.assert_called_with("connection", "delete", "uuid", FALLBACK_UUID)
        self.assertFalse(any("up" in call.args for call in self.a.nm.call_args_list))

    def test_readback_failure_deletes_only_owned_profile(self):
        self.a.observe.side_effect = [self.empty, self.empty, self.empty]
        with self.assertRaises(SafetyError):
            self.a.start_fallback(PRIMARY, elapsed=30, verified_wired_gate=True)
        self.a.nm.assert_called_with("connection", "delete", "uuid", FALLBACK_UUID)

    def test_restore_requires_safe_retry(self):
        with self.assertRaises(SafetyError):
            self.a.restore_primary(PRIMARY, verified_wired_gate=True, retry_safe=False)
        self.a.nm.assert_not_called()

    def test_restore_primary_deletes_fallback_after_success(self):
        primary = replace(self.empty, ipv4_addresses=("192.0.2.10/24",), default_route=True)
        self.a.observe.side_effect = [self.fallback, primary]
        self.assertEqual(self.a.restore_primary(PRIMARY, verified_wired_gate=True, retry_safe=True), primary)
        self.a.nm.assert_called_with("connection", "delete", "uuid", FALLBACK_UUID)

    def test_failed_retry_restores_fallback_and_reports_failure(self):
        self.a.observe.side_effect = [self.fallback, self.empty, self.empty, self.fallback]
        self.a.nm.side_effect = [subprocess.CalledProcessError(1, "nmcli"), ""]
        with self.assertRaises(SafetyError):
            self.a.restore_primary(PRIMARY, verified_wired_gate=True, retry_safe=True)
        self.a.nm.assert_called_with("--wait", "30", "connection", "up", "uuid", FALLBACK_UUID, "ifname", "eth0")


if __name__ == "__main__":
    unittest.main()

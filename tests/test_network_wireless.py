import json
import unittest
from dataclasses import replace
from unittest.mock import Mock
import subprocess

from pi_player.network_actuator import WiredObservation, SafetyError, NM, IP
from pi_player.network_wireless import (
    WirelessActuator, WirelessObservation, CLIENT_UUID, HOTSPOT_UUID,
    CLIENT_NAME, HOTSPOT_NAME, IW,
)
from pi_player.network_gate import Gate
from pi_player.network_policy import WirelessRole, HOTSPOT_ADDRESS


class WirelessActuatorTests(unittest.TestCase):
    def setUp(self):
        self.a = WirelessActuator(gate_verified=Mock(return_value=True),
                                  dhcp_stopped=Mock(return_value=True), sleep=Mock())
        self.off = WirelessObservation(False, 20, None, WirelessRole.OFF, (), False)
        self.client = WirelessObservation(True, 100, CLIENT_UUID, WirelessRole.CLIENT,
                                          ("192.0.2.20/24",), True)
        self.ap = WirelessObservation(True, 100, HOTSPOT_UUID, WirelessRole.HOTSPOT,
                                      (HOTSPOT_ADDRESS,), False)
        self.wired_off = WiredObservation(False, None, (), False, True)
        self.wired_on = WiredObservation(True, "wired", ("192.0.2.10/24",), True, True)
        self.a.observe = Mock(return_value=self.wired_off)
        self.a.observe_wireless = Mock(return_value=self.off)
        self.a.routes = Mock(return_value=[])
        self.a.nm = Mock(return_value="")
        self.a.run = Mock(return_value="Interface wlan0\n\ttype AP\n")
        self.a.wait_ready = Mock()
        self.a.verify_owned_profiles = Mock()
        self.a.validate_profile = Mock(side_effect=lambda role:
                                       HOTSPOT_UUID if role == WirelessRole.HOTSPOT else CLIENT_UUID)

    def test_read_only_wireless_observer(self):
        responses = {
            (NM, "radio", "wifi"): "disabled",
            (NM, "-g", "GENERAL.STATE", "device", "show", "wlan0"): "20 (unavailable)",
            (NM, "-t", "-f", "UUID,DEVICE", "connection", "show", "--active"): "uuid:eth0",
            (IP, "-j", "-4", "address", "show", "dev", "wlan0"): json.dumps([{"addr_info": []}]),
            (IP, "-j", "-4", "route", "show", "table", "all"): "[]",
        }
        runner = Mock(side_effect=lambda args, **kw: subprocess.CompletedProcess(args, 0, responses[tuple(args)], ""))
        self.assertEqual(WirelessActuator(runner=runner).observe_wireless(), self.off)
        self.assertEqual(runner.call_count, 5)

    def test_unknown_wireless_profile_observed_as_unknown(self):
        a = WirelessActuator()
        a.nm = Mock(side_effect=["enabled", "100 (connected)", "foreign:wlan0"])
        a.run = Mock(return_value="[]")
        self.assertIsNone(a.observe_wireless().role)

    def test_owned_profiles_only(self):
        a = WirelessActuator()
        a.nm = Mock(return_value="foreign:802-11-wireless")
        with self.assertRaises(SafetyError):
            a.verify_owned_profiles()
        a.nm.return_value = CLIENT_UUID + ":wifi"
        a.field = Mock(return_value="yes")
        with self.assertRaises(SafetyError):
            a.verify_owned_profiles()
        a.field.return_value = "no"
        a.verify_owned_profiles()

    def test_client_profile_disallows_shared(self):
        a = WirelessActuator()
        fields = {"connection.id": CLIENT_NAME, "connection.type": "802-11-wireless",
                  "connection.interface-name": "wlan0", "connection.autoconnect": "no",
                  "802-11-wireless.mode": "infrastructure",
                  "802-11-wireless-security.key-mgmt": "wpa-psk",
                  "ipv6.method": "disabled", "ipv4.method": "shared"}
        a.field = Mock(side_effect=lambda profile, field: fields[field])
        with self.assertRaises(SafetyError):
            a.validate_profile(WirelessRole.CLIENT)
        fields["ipv4.method"] = "auto"
        self.assertEqual(a.validate_profile(WirelessRole.CLIENT), CLIENT_UUID)

    def test_ap_profile_isolation_and_wps(self):
        a = WirelessActuator()
        fields = {"connection.id": HOTSPOT_NAME, "connection.type": "802-11-wireless",
                  "connection.interface-name": "wlan0", "connection.autoconnect": "no",
                  "802-11-wireless.mode": "ap", "802-11-wireless.band": "bg",
                  "802-11-wireless.channel": "6", "802-11-wireless.ap-isolation": "1",
                  "802-11-wireless-security.key-mgmt": "wpa-psk",
                  "802-11-wireless-security.proto": "rsn",
                  "802-11-wireless-security.pairwise": "ccmp",
                  "802-11-wireless-security.group": "ccmp",
                  "802-11-wireless-security.wps-method": "1",
                  "ipv6.method": "disabled", "ipv4.method": "manual",
                  "ipv4.addresses": HOTSPOT_ADDRESS, "ipv4.never-default": "yes",
                  "ipv4.gateway": "", "ipv4.dns": ""}
        a.field = Mock(side_effect=lambda profile, field: fields[field])
        self.assertEqual(a.validate_profile(WirelessRole.HOTSPOT), HOTSPOT_UUID)
        fields["802-11-wireless.ap-isolation"] = "0"
        with self.assertRaises(SafetyError):
            a.validate_profile(WirelessRole.HOTSPOT)
        fields["802-11-wireless.ap-isolation"] = "1"
        fields["802-11-wireless-security.wps-method"] = "0"
        with self.assertRaises(SafetyError):
            a.validate_profile(WirelessRole.HOTSPOT)

    def test_authorization_and_gate_required(self):
        with self.assertRaises(SafetyError):
            self.a.start(WirelessRole.CLIENT)
        self.a.gate_verified.return_value = False
        with self.assertRaises(SafetyError):
            self.a.start(WirelessRole.CLIENT, authorized=True)
        self.a.nm.assert_not_called()

    def test_client_denies_carrier_unknown_or_wired_profile(self):
        for wired in (self.wired_on, replace(self.wired_off, carrier=None),
                      replace(self.wired_off, active_uuid="wired")):
            self.a.observe.return_value = wired
            with self.assertRaises(SafetyError):
                self.a.start(WirelessRole.CLIENT, authorized=True)
        self.a.nm.assert_not_called()

    def test_client_start_success(self):
        self.a.observe_wireless.side_effect = [self.off, self.off, self.client]
        self.assertEqual(self.a.start(WirelessRole.CLIENT, authorized=True), self.client)
        self.a.gate_verified.assert_called_with(Gate.CLIENT)
        self.a.nm.assert_called_with("--wait", "30", "connection", "up", "uuid", CLIENT_UUID, "ifname", "wlan0")

    def test_cable_insertion_before_activation(self):
        self.a.observe.side_effect = [self.wired_off, self.wired_on]
        with self.assertRaises(SafetyError):
            self.a.start(WirelessRole.CLIENT, authorized=True)
        self.assertEqual([c.args for c in self.a.nm.call_args_list],
                         [("radio", "wifi", "on"), ("radio", "wifi", "off")])

    def test_cable_insertion_during_activation(self):
        self.a.observe.side_effect = [self.wired_off, self.wired_off, self.wired_on]
        self.a.observe_wireless.side_effect = [self.off, self.off, self.client]
        with self.assertRaises(SafetyError):
            self.a.start(WirelessRole.CLIENT, authorized=True)
        self.a.nm.assert_called_with("radio", "wifi", "off")

    def test_ap_with_wired_connection(self):
        self.a.observe.return_value = self.wired_on
        self.a.observe_wireless.side_effect = [self.off, self.off, self.ap]
        self.assertEqual(self.a.start(WirelessRole.HOTSPOT, authorized=True), self.ap)
        self.a.gate_verified.assert_called_with(Gate.HOTSPOT)
        self.a.run.assert_called_with(IW, "dev", "wlan0", "info")

    def test_ap_subnet_conflict_and_dhcp_running(self):
        self.a.routes.return_value = [{"dst": "10.42.0.0/16"}]
        with self.assertRaises(SafetyError):
            self.a.start(WirelessRole.HOTSPOT, authorized=True)
        self.a.routes.return_value = []
        self.a.dhcp_stopped.return_value = False
        with self.assertRaises(SafetyError):
            self.a.start(WirelessRole.HOTSPOT, authorized=True)
        self.a.nm.assert_not_called()

    def test_ap_wrong_mode_or_default_route(self):
        for observed, iw in ((self.ap, "type managed"), (replace(self.ap, default_route=True), "type AP")):
            self.a.observe_wireless.side_effect = [self.off, self.off, observed]
            self.a.run.return_value = iw
            with self.assertRaises(SafetyError):
                self.a.start(WirelessRole.HOTSPOT, authorized=True)
            self.a.nm.assert_called_with("radio", "wifi", "off")

    def test_stop_requires_dhcp_shutdown_and_verified_teardown(self):
        self.a.dhcp_stopped.return_value = False
        with self.assertRaises(SafetyError):
            self.a.stop()
        self.a.nm.assert_not_called()
        self.a.dhcp_stopped.return_value = True
        self.a.observe_wireless.return_value = self.ap
        with self.assertRaises(SafetyError):
            self.a.stop()
        self.a.observe_wireless.return_value = self.off
        self.assertEqual(self.a.stop(), self.off)

    def test_readiness_wait_bounded(self):
        a = WirelessActuator(sleep=Mock())
        a.nm = Mock(side_effect=["20 (unavailable)", "30 (disconnected)"])
        a.wait_ready()
        a.sleep.assert_called_once_with(1)
        a.nm.side_effect = None
        a.nm.return_value = "20 (unavailable)"
        with self.assertRaises(SafetyError):
            a.wait_ready()


if __name__ == "__main__":
    unittest.main()

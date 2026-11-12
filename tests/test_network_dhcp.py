import unittest
from dataclasses import replace
from unittest.mock import Mock

from pi_player.network_actuator import SafetyError, WiredObservation
from pi_player.network_dhcp import (
    HotspotDHCP, ServiceState, render_service_config,
    UNIT, SYSTEMCTL, DNSMASQ, CONFIG_PATH,
)
from pi_player.network_gate import Gate
from pi_player.network_policy import HOTSPOT_ADDRESS, WirelessRole
from pi_player.network_wireless import WirelessObservation, HOTSPOT_UUID, IW


class HotspotDHCPTests(unittest.TestCase):
    def setUp(self):
        self.wireless = Mock()
        self.gate = Mock(return_value=True)
        self.host = Mock(return_value=True)
        self.config = Mock(return_value=True)
        self.a = HotspotDHCP(wireless=self.wireless, gate_verified=self.gate,
                             host_ready=self.host, config_verified=self.config)
        self.ap = WirelessObservation(True, 100, HOTSPOT_UUID, WirelessRole.HOTSPOT,
                                      (HOTSPOT_ADDRESS,), False)
        self.wireless.observe_wireless.return_value = self.ap
        self.wireless.observe.return_value = WiredObservation(True, "wired", ("192.0.2.10/24",), True, False)
        self.wireless.run.return_value = "Interface wlan0\n\ttype AP\n"
        self.running = ServiceState("loaded", "active", "running", 123, 0, "0")
        self.off = ServiceState("loaded", "inactive", "dead", 0, 0, "0")
        self.a.status = Mock(return_value=self.off)

    def test_config_has_no_dns_gateway_or_ethernet_dhcp(self):
        config = render_service_config()
        for line in ("port=0", "interface=wlan0", "bind-interfaces", "except-interface=eth0",
                     "no-dhcp-interface=eth0", "dhcp-range=10.42.0.2,10.42.0.3,255.255.255.0,1h",
                     "dhcp-lease-max=2", "dhcp-option=option:router", "dhcp-option=option:dns-server"):
            self.assertIn(line, config.splitlines())
        self.assertNotIn("log-dhcp", config)

    def test_read_only_status_parser(self):
        a = HotspotDHCP(wireless=self.wireless)
        self.wireless.run.return_value = (
            "LoadState=loaded\nActiveState=active\nSubState=running\nMainPID=123\nControlPID=0\nJob=0\n")
        self.assertEqual(a.status(), self.running)
        self.wireless.run.assert_called_once_with(SYSTEMCTL, "show", UNIT,
            "--property=LoadState,ActiveState,SubState,MainPID,ControlPID,Job")
        self.wireless.run.return_value = "ActiveState=inactive\n"
        with self.assertRaises(SafetyError):
            a.status()

    def test_stopped_requires_no_pending_job_or_process(self):
        self.assertTrue(self.off.stopped)
        self.assertTrue(replace(self.off, load="not-found").stopped)
        self.assertFalse(replace(self.off, job="17").stopped)
        self.assertFalse(replace(self.off, control_pid=55).stopped)
        self.assertFalse(replace(self.off, main_pid=55).stopped)
        self.assertFalse(replace(self.running, job="17").running)

    def test_authorization_required(self):
        with self.assertRaises(SafetyError):
            self.a.start()
        self.wireless.run.assert_not_called()

    def test_gate_host_and_config_required(self):
        for check in (self.gate, self.host, self.config):
            check.return_value = False
            with self.assertRaises(SafetyError):
                self.a.start(authorized=True)
            check.return_value = True
        self.wireless.run.assert_not_called()

    def test_only_active_verified_hotspot(self):
        for obs in (replace(self.ap, radio_enabled=False), replace(self.ap, device_state=70),
                    replace(self.ap, role=WirelessRole.CLIENT), replace(self.ap, active_uuid="foreign"),
                    replace(self.ap, ipv4_addresses=()), replace(self.ap, default_route=True)):
            self.wireless.observe_wireless.return_value = obs
            with self.assertRaises(SafetyError):
                self.a.start(authorized=True)
        self.wireless.run.assert_not_called()

    def test_kernel_ap_and_known_carrier(self):
        self.wireless.observe.return_value = WiredObservation(None, None, (), False, False)
        with self.assertRaises(SafetyError):
            self.a.start(authorized=True)
        self.wireless.observe.return_value = WiredObservation(False, None, (), False, False)
        self.wireless.run.return_value = "type managed"
        with self.assertRaises(SafetyError):
            self.a.start(authorized=True)
        self.wireless.run.assert_called_with(IW, "dev", "wlan0", "info")

    def test_successful_start_validates_before_and_after(self):
        self.a.status.side_effect = [self.off, self.running]
        self.assertEqual(self.a.start(authorized=True), self.running)
        self.gate.assert_called_with(Gate.HOTSPOT)
        self.assertEqual(self.gate.call_count, 3)
        self.wireless.run.assert_any_call(DNSMASQ, "--test", f"--conf-file={CONFIG_PATH}")
        self.wireless.run.assert_any_call(SYSTEMCTL, "start", UNIT)

    def test_missing_unit_not_started(self):
        self.a.status.return_value = replace(self.off, load="not-found")
        with self.assertRaises(SafetyError):
            self.a.start(authorized=True)
        self.wireless.run.assert_not_called()

    def test_gate_lost_after_start_stops_service(self):
        self.gate.side_effect = [True, True, False]
        self.a.status.side_effect = [self.off, self.off]
        with self.assertRaises(SafetyError):
            self.a.start(authorized=True)
        self.wireless.run.assert_any_call(SYSTEMCTL, "start", UNIT)
        self.wireless.run.assert_called_with(SYSTEMCTL, "stop", UNIT)

    def test_failed_start_stops_service(self):
        self.a.status.side_effect = [self.off, self.off, self.off]
        with self.assertRaises(SafetyError):
            self.a.start(authorized=True)
        self.wireless.run.assert_called_with(SYSTEMCTL, "stop", UNIT)

    def test_reconcile_stops_on_unknown_or_wrong_ap(self):
        self.a.status.side_effect = [self.running, self.off]
        self.wireless.observe_wireless.return_value = replace(self.ap, role=WirelessRole.CLIENT)
        with self.assertRaises(SafetyError):
            self.a.reconcile()
        self.wireless.run.assert_called_with(SYSTEMCTL, "stop", UNIT)

    def test_stop_requires_actual_shutdown(self):
        self.a.status.return_value = self.running
        with self.assertRaises(SafetyError):
            self.a.stop()
        self.a.status.return_value = self.off
        self.assertEqual(self.a.stop(), self.off)


if __name__ == "__main__":
    unittest.main()

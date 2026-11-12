import unittest
from dataclasses import replace

from pi_player.network_policy import HotspotMode, WirelessRole
from pi_player.network_controller import Action, Config, Snapshot, WiredRole, plan


class NetworkControllerTests(unittest.TestCase):
    def setUp(self):
        self.cfg = Config()
        self.wired = Snapshot(carrier=True, wired=WiredRole.PRIMARY,
                              primary_address=True, interlock_ready=True)
        self.empty = Snapshot(carrier=False, interlock_ready=True, uplinks_blocked=True)

    def check(self, cfg, snapshot, expected):
        self.assertEqual(plan(cfg, snapshot).action, expected)

    def test_normal_wired(self):
        self.check(self.cfg, self.wired, Action.HOLD)
        self.check(replace(self.cfg, wifi_configured=True), self.wired, Action.HOLD)

    def test_start_primary(self):
        self.check(self.cfg, replace(self.empty, carrier=True), Action.START_PRIMARY)

    def test_fallback_at_timeout(self):
        s = replace(self.wired, primary_address=False, dhcp_elapsed=29)
        self.check(self.cfg, s, Action.HOLD)
        s = replace(s, dhcp_elapsed=30)
        self.check(self.cfg, s, Action.START_FALLBACK)
        self.check(replace(self.cfg, ethernet_dhcp=False), s, Action.HOLD)
        self.check(self.cfg, replace(s, fallback_conflict=True), Action.HOLD)

    def test_retry_wired_only_if_safe_and_due(self):
        s = replace(self.wired, wired=WiredRole.FALLBACK, primary_address=False,
                    fallback_address=True, retry_elapsed=300)
        self.check(self.cfg, s, Action.HOLD)
        self.check(self.cfg, replace(s, retry_safe=True, retry_elapsed=299), Action.HOLD)
        self.check(self.cfg, replace(s, retry_safe=True), Action.RESTORE_PRIMARY)
        self.check(self.cfg, replace(s, fallback_conflict=True), Action.RESTORE_PRIMARY)
        self.check(replace(self.cfg, ethernet_dhcp=False), s, Action.RESTORE_PRIMARY)

    def test_unplug_break_before_make(self):
        cfg = replace(self.cfg, wifi_configured=True)
        s = replace(self.wired, carrier=False)
        self.check(cfg, s, Action.BLOCK_UPLINKS)
        self.check(cfg, replace(s, uplinks_blocked=True), Action.STOP_WIRED)
        self.check(cfg, self.empty, Action.START_CLIENT)

    def test_cable_reconnect_break_before_make(self):
        cfg = replace(self.cfg, wifi_configured=True)
        s = replace(self.empty, wireless=WirelessRole.CLIENT, wifi_address=True,
                    uplinks_blocked=False, carrier=True)
        self.check(cfg, s, Action.BLOCK_UPLINKS)
        s = replace(s, uplinks_blocked=True)
        self.check(cfg, s, Action.STOP_WIRELESS)
        self.check(cfg, replace(s, wireless=WirelessRole.OFF), Action.START_PRIMARY)
        self.check(cfg, replace(self.wired, uplinks_blocked=True), Action.ALLOW_WIRED)

    def test_no_client_if_wired_active_without_carrier(self):
        cfg = replace(self.cfg, wifi_configured=True)
        s = replace(self.wired, carrier=False, wireless=WirelessRole.CLIENT)
        self.check(cfg, s, Action.BLOCK_UPLINKS)

    def test_unknown_carrier_and_interlock(self):
        cfg = replace(self.cfg, wifi_configured=True)
        self.check(cfg, replace(self.empty, carrier=None, uplinks_blocked=False), Action.BLOCK_UPLINKS)
        self.check(cfg, replace(self.empty, carrier=None), Action.HOLD)
        self.check(cfg, replace(self.empty, interlock_ready=False), Action.HOLD)

    def test_hotspot_isolation_before_activation(self):
        cfg = replace(self.cfg, hotspot_mode=HotspotMode.PERMANENT, hotspot_credentials_valid=True)
        self.check(cfg, self.wired, Action.INSTALL_HOTSPOT_ISOLATION)
        self.check(cfg, replace(self.wired, hotspot_isolated=True), Action.START_HOTSPOT)
        self.check(cfg, replace(self.wired, hotspot_isolated=True, wireless=WirelessRole.HOTSPOT), Action.HOLD)
        self.check(cfg, replace(self.wired, hotspot_isolated=True, wireless=WirelessRole.HOTSPOT,
                                hotspot_address=True), Action.START_HOTSPOT_DHCP)
        self.check(replace(cfg, hotspot_credentials_valid=False), self.wired, Action.HOLD)

    def test_dhcp_stops_on_isolation_loss(self):
        cfg = replace(self.cfg, hotspot_mode=HotspotMode.PERMANENT, hotspot_credentials_valid=True)
        s = replace(self.wired, wireless=WirelessRole.HOTSPOT, hotspot_address=True,
                    hotspot_dhcp_running=True, hotspot_isolated=False)
        self.check(cfg, s, Action.STOP_HOTSPOT_DHCP)
        self.check(cfg, replace(s, hotspot_dhcp_running=False), Action.STOP_WIRELESS)

    def test_dhcp_never_allowed_on_client_or_wired(self):
        for role in (WirelessRole.CLIENT, WirelessRole.OFF):
            self.check(self.cfg, replace(self.wired, wireless=role, hotspot_dhcp_running=True),
                       Action.STOP_HOTSPOT_DHCP)

    def test_recovery_prefers_fallback(self):
        cfg = replace(self.cfg, hotspot_mode=HotspotMode.RECOVERY, hotspot_credentials_valid=True)
        s = replace(self.wired, primary_address=False, dhcp_elapsed=30)
        self.check(cfg, s, Action.START_FALLBACK)
        self.check(cfg, replace(s, wired=WiredRole.FALLBACK, fallback_address=True), Action.HOLD)
        self.check(cfg, replace(s, fallback_conflict=True), Action.INSTALL_HOTSPOT_ISOLATION)

    def test_wireless_recovery_timeout_and_safe_retry(self):
        cfg = replace(self.cfg, hotspot_mode=HotspotMode.RECOVERY,
                      hotspot_credentials_valid=True, wifi_configured=True)
        self.check(cfg, self.empty, Action.START_CLIENT)
        s = replace(self.empty, wireless=WirelessRole.CLIENT, uplinks_blocked=False, wifi_elapsed=30)
        self.check(cfg, s, Action.STOP_WIRELESS)
        s = replace(s, wireless=WirelessRole.HOTSPOT, wifi_failed=True,
                    hotspot_address=True, hotspot_isolated=True, hotspot_dhcp_running=True,
                    retry_elapsed=300)
        self.check(cfg, s, Action.HOLD)
        self.check(cfg, replace(s, retry_safe=True), Action.STOP_HOTSPOT_DHCP)
        self.check(cfg, replace(s, retry_safe=True, hotspot_dhcp_running=False), Action.RETRY_CLIENT)


if __name__ == "__main__":
    unittest.main()

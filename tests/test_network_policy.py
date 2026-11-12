import unittest
from dataclasses import replace

from pi_player.network_policy import (
    NetworkFacts, HotspotMode, WirelessRole, decide,
    generate_hotspot_password, validate_hotspot_credentials,
    HOTSPOT_SSID, HOTSPOT_LEASE_SECONDS, ETHERNET_DHCP_TIMEOUT,
)


class NetworkPolicyTests(unittest.TestCase):
    def setUp(self):
        self.base = NetworkFacts(ethernet_carrier=True, ethernet_has_address=True,
                                 wifi_configured=True)

    def test_wired_interlock_exhaustive(self):
        for mode in HotspotMode:
            for addr in (False, True):
                for expired in (False, True):
                    for ready in (False, True):
                        facts = replace(self.base, hotspot_mode=mode, ethernet_has_address=addr,
                                        ethernet_dhcp_expired=expired, hotspot_credentials_valid=ready,
                                        hotspot_isolation_ready=ready)
                        self.assertNotEqual(decide(facts).wireless, WirelessRole.CLIENT)

    def test_unknown_carrier_fails_closed(self):
        facts = replace(self.base, ethernet_carrier=None, hotspot_mode=HotspotMode.PERMANENT,
                        hotspot_credentials_valid=True, hotspot_isolation_ready=True)
        self.assertEqual(decide(facts).wireless, WirelessRole.OFF)
        self.assertFalse(decide(facts).ethernet_fallback)

    def test_dhcp_fallback_only_after_timeout(self):
        facts = replace(self.base, ethernet_has_address=False)
        self.assertFalse(decide(facts).ethernet_fallback)
        facts = replace(facts, ethernet_dhcp_expired=True)
        self.assertTrue(decide(facts).ethernet_fallback)
        self.assertFalse(decide(replace(facts, ethernet_dhcp=False)).ethernet_fallback)
        self.assertFalse(decide(replace(facts, fallback_conflict=True)).ethernet_fallback)
        self.assertFalse(decide(replace(facts, ethernet_carrier=False)).ethernet_fallback)
        self.assertFalse(decide(replace(facts, ethernet_has_address=True)).ethernet_fallback)

    def test_client_only_without_carrier(self):
        facts = replace(self.base, ethernet_carrier=False, ethernet_has_address=False)
        self.assertEqual(decide(facts).wireless, WirelessRole.CLIENT)
        self.assertEqual(decide(replace(facts, ethernet_carrier=True)).wireless, WirelessRole.OFF)

    def test_hotspot_gate_and_modes(self):
        facts = replace(self.base, hotspot_mode=HotspotMode.PERMANENT)
        self.assertEqual(decide(facts).wireless, WirelessRole.OFF)
        facts = replace(facts, hotspot_credentials_valid=True, hotspot_isolation_ready=True)
        self.assertEqual(decide(facts).wireless, WirelessRole.HOTSPOT)
        self.assertEqual(decide(replace(facts, hotspot_isolation_ready=False)).wireless, WirelessRole.OFF)
        self.assertEqual(decide(replace(facts, hotspot_credentials_valid=False)).wireless, WirelessRole.OFF)
        self.assertEqual(decide(replace(facts, hotspot_mode=HotspotMode.DISABLED)).wireless, WirelessRole.OFF)

    def test_recovery_prefers_healthy_management(self):
        facts = replace(self.base, hotspot_mode=HotspotMode.RECOVERY,
                        hotspot_credentials_valid=True, hotspot_isolation_ready=True)
        self.assertEqual(decide(facts).wireless, WirelessRole.OFF)
        self.assertEqual(decide(replace(facts, ethernet_carrier=False)).wireless, WirelessRole.CLIENT)
        self.assertEqual(decide(replace(facts, ethernet_carrier=False, wifi_failed=True)).wireless, WirelessRole.HOTSPOT)
        self.assertEqual(decide(replace(facts, ethernet_has_address=False, ethernet_dhcp_expired=True)).wireless, WirelessRole.OFF)

    def test_credentials(self):
        first, second = generate_hotspot_password(), generate_hotspot_password()
        self.assertRegex(first, r"^[0-9a-f]{24}$")
        self.assertNotEqual(first, second)
        validate_hotspot_credentials(HOTSPOT_SSID, first)
        for ssid, password in [("", first), ("a"*33, first), ("x\n", first), ("ok", ""), ("ok", "a"*64)]:
            with self.assertRaises(ValueError):
                validate_hotspot_credentials(ssid, password)
        self.assertEqual(HOTSPOT_LEASE_SECONDS, 3600)
        self.assertEqual(ETHERNET_DHCP_TIMEOUT, 30)


if __name__ == "__main__":
    unittest.main()

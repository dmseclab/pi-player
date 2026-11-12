"""Pure network commissioning policy; no OS changes or credentials persisted here."""
from dataclasses import dataclass
from enum import Enum
import secrets

HOTSPOT_SSID = "pi-player-local"
HOTSPOT_ADDRESS = "10.42.0.1/24"
HOTSPOT_DHCP_START = "10.42.0.2"
HOTSPOT_DHCP_END = "10.42.0.3"
HOTSPOT_LEASE_SECONDS = 3600
ETHERNET_FALLBACK = "10.42.1.1/24"
ETHERNET_DHCP_TIMEOUT = 30


class HotspotMode(str, Enum):
    DISABLED = "disabled"
    PERMANENT = "permanent"
    RECOVERY = "recovery"


class WirelessRole(str, Enum):
    OFF = "off"
    CLIENT = "client"
    HOTSPOT = "hotspot"


@dataclass(frozen=True)
class NetworkFacts:
    ethernet_carrier: bool
    ethernet_has_address: bool
    ethernet_dhcp: bool = True
    ethernet_dhcp_expired: bool = False
    wifi_configured: bool = False
    wifi_failed: bool = False
    hotspot_mode: HotspotMode = HotspotMode.DISABLED
    hotspot_credentials_valid: bool = False
    hotspot_isolation_ready: bool = False
    fallback_conflict: bool = False


@dataclass(frozen=True)
class NetworkDecision:
    wireless: WirelessRole
    ethernet_fallback: bool
    reason: str


def decide(facts: NetworkFacts) -> NetworkDecision:
    """Return desired role only; an OS controller must enforce transition interlocks.

    A wired fallback address counts as a local management path, not an Internet
    connection. Never start a DHCP server on Ethernet. Unknown carrier must be
    handled as a closed interlock by the caller, not coerced to False.
    """
    fallback = (
        facts.ethernet_carrier and facts.ethernet_dhcp
        and not facts.ethernet_has_address and facts.ethernet_dhcp_expired
        and not facts.fallback_conflict
    )
    mode = HotspotMode(facts.hotspot_mode)
    ap_ready = facts.hotspot_credentials_valid and facts.hotspot_isolation_ready
    if mode == HotspotMode.PERMANENT:
        return NetworkDecision(
            WirelessRole.HOTSPOT if ap_ready else WirelessRole.OFF,
            fallback, "permanent hotspot" if ap_ready else "hotspot safety gate closed"
        )
    if facts.ethernet_carrier:
        # Even failed DHCP or static configuration must not permit client Wi-Fi.
        if (mode == HotspotMode.RECOVERY and not facts.ethernet_has_address
                and not fallback and facts.ethernet_dhcp_expired and ap_ready):
            return NetworkDecision(WirelessRole.HOTSPOT, False, "wired management unavailable")
        return NetworkDecision(WirelessRole.OFF, fallback, "ethernet interlock")
    if facts.wifi_configured and not facts.wifi_failed:
        return NetworkDecision(WirelessRole.CLIENT, False, "configured wireless uplink")
    if mode == HotspotMode.RECOVERY and ap_ready:
        return NetworkDecision(WirelessRole.HOTSPOT, False, "management uplinks unavailable")
    return NetworkDecision(WirelessRole.OFF, False, "no permitted wireless role")


def generate_hotspot_password() -> str:
    """24 hexadecimal characters / 96 random bits; never log the returned value."""
    return secrets.token_hex(12)


def validate_hotspot_credentials(ssid: str, password: str) -> None:
    if not 1 <= len(ssid.encode("utf-8")) <= 32 or any(ord(c) < 32 or ord(c) == 127 for c in ssid):
        raise ValueError("Invalid hotspot SSID")
    if not 12 <= len(password) <= 63 or any(not 32 <= ord(c) <= 126 for c in password):
        raise ValueError("Hotspot password must contain 12–63 printable ASCII characters")

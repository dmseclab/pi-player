"""Reconciliation plan for a future privileged network actuator.

No command execution, file writes or service activation. Each action requires
a fresh observed snapshot before the next action is issued. In particular an
event-driven loop is not an atomic carrier interlock: the actuator must hold
kernel traffic gates and disable independent autoconnect.
"""
from dataclasses import dataclass
from enum import Enum

from .network_policy import HotspotMode, WirelessRole, ETHERNET_DHCP_TIMEOUT

WIFI_TIMEOUT = 30
RETRY_DELAY = 300


class WiredRole(str, Enum):
    OFF = "off"
    PRIMARY = "primary"
    FALLBACK = "fallback"


class Action(str, Enum):
    HOLD = "hold"
    BLOCK_UPLINKS = "block-uplinks"
    ALLOW_WIRED = "allow-wired-only"
    ALLOW_CLIENT = "allow-client-only"
    RETRY_CLIENT = "retry-client"
    STOP_HOTSPOT_DHCP = "stop-hotspot-dhcp"
    STOP_WIRELESS = "stop-wireless"
    STOP_WIRED = "stop-wired"
    START_PRIMARY = "start-primary"
    START_FALLBACK = "start-fallback"
    RESTORE_PRIMARY = "restore-primary"
    START_CLIENT = "start-client"
    INSTALL_HOTSPOT_ISOLATION = "install-hotspot-isolation"
    START_HOTSPOT = "start-hotspot"
    START_HOTSPOT_DHCP = "start-hotspot-dhcp"


@dataclass(frozen=True)
class Config:
    ethernet_dhcp: bool = True
    wifi_configured: bool = False
    hotspot_mode: HotspotMode = HotspotMode.DISABLED
    hotspot_credentials_valid: bool = False


@dataclass(frozen=True)
class Snapshot:
    carrier: bool | None = None
    wired: WiredRole = WiredRole.OFF
    wireless: WirelessRole = WirelessRole.OFF
    primary_address: bool = False
    fallback_address: bool = False
    fallback_conflict: bool = False
    dhcp_elapsed: float = 0
    wifi_elapsed: float = 0
    wifi_address: bool = False
    wifi_failed: bool = False
    # Actual kernel enforcement, NOT merely a requested configuration.
    interlock_ready: bool = False
    uplinks_blocked: bool = False
    hotspot_isolated: bool = False
    hotspot_address: bool = False
    hotspot_dhcp_running: bool = False
    # True only when the actuator can establish no active commissioning session.
    retry_safe: bool = False
    retry_elapsed: float = 0


@dataclass(frozen=True)
class Plan:
    action: Action
    reason: str


def plan(config: Config, s: Snapshot) -> Plan:
    """Return one ordered action. A failed/unknown observation must not authorize
    activation. A future actuator must recheck preconditions immediately before
    applying each action and acknowledge actual results, not intended state.
    """
    def p(action, reason):
        return Plan(action, reason)

    # Stop DHCP before dismantling an AP; DHCP must never follow a client role.
    if s.hotspot_dhcp_running and (
        s.wireless != WirelessRole.HOTSPOT or not s.hotspot_isolated
        or not s.hotspot_address or not s.interlock_ready
        or type(s.carrier) is not bool
        or config.hotspot_mode == HotspotMode.DISABLED
        or not config.hotspot_credentials_valid
    ):
        return p(Action.STOP_HOTSPOT_DHCP, "hotspot DHCP safety gate closed")
    if type(s.carrier) is not bool or not s.interlock_ready:
        if not s.uplinks_blocked:
            return p(Action.BLOCK_UPLINKS, "interlock not verified or carrier unknown")
        if s.wireless != WirelessRole.OFF:
            return p(Action.STOP_WIRELESS, "interlock not verified or carrier unknown")
        return p(Action.HOLD, "await verified interlock and carrier")
    if s.wireless == WirelessRole.HOTSPOT and not s.hotspot_isolated:
        return p(Action.STOP_WIRELESS, "hotspot isolation lost")
    # Cable insertion must never enable wired traffic until the client is down.
    if s.wireless == WirelessRole.CLIENT and (s.carrier or s.wired != WiredRole.OFF):
        if not s.uplinks_blocked:
            return p(Action.BLOCK_UPLINKS, "wired/client overlap or cable insertion")
        return p(Action.STOP_WIRELESS, "break before make: stop client")
    # Permanent mode preempts client connectivity, even without Ethernet.
    if s.wireless == WirelessRole.CLIENT and (
        config.hotspot_mode == HotspotMode.PERMANENT or not config.wifi_configured
    ):
        return p(Action.STOP_WIRELESS, "client no longer permitted")

    if s.carrier:
        if s.wired != WiredRole.OFF and s.uplinks_blocked:
            return p(Action.ALLOW_WIRED, "client stopped; wired gate only")
        if s.wired == WiredRole.OFF:
            return p(Action.START_PRIMARY, "carrier present; primary wired profile first")
        if s.wired == WiredRole.FALLBACK:
            if not config.ethernet_dhcp or s.fallback_conflict or not s.fallback_address:
                return p(Action.RESTORE_PRIMARY, "fallback invalid or static selected")
            if s.retry_safe and s.retry_elapsed >= RETRY_DELAY:
                return p(Action.RESTORE_PRIMARY, "bounded DHCP retry; no commissioning session")
        elif (config.ethernet_dhcp and not s.primary_address
              and s.dhcp_elapsed >= ETHERNET_DHCP_TIMEOUT and not s.fallback_conflict):
            return p(Action.START_FALLBACK, "DHCP expired; duplicate-address check required")
    elif s.wired != WiredRole.OFF:
        if not s.uplinks_blocked:
            return p(Action.BLOCK_UPLINKS, "carrier removed; close gate before wired teardown")
        return p(Action.STOP_WIRED, "carrier absent; remove wired profile before client")
    elif s.wireless == WirelessRole.CLIENT and s.uplinks_blocked:
        return p(Action.ALLOW_CLIENT, "wired profile stopped; client gate only")

    wired_ok = s.carrier and (
        (s.wired == WiredRole.PRIMARY and s.primary_address)
        or (s.wired == WiredRole.FALLBACK and s.fallback_address and not s.fallback_conflict)
    )
    wifi_ok = (s.wireless == WirelessRole.CLIENT and s.wifi_address and not s.wifi_failed)
    wifi_exhausted = s.wifi_failed or (
        s.wireless == WirelessRole.CLIENT and not wifi_ok and s.wifi_elapsed >= WIFI_TIMEOUT
    )
    mode = HotspotMode(config.hotspot_mode)
    if mode == HotspotMode.PERMANENT:
        target = WirelessRole.HOTSPOT
    elif s.carrier:
        # Do not interrupt DHCP acquisition. A static failure needs the same
        # bounded observation period, but cannot cause automatic wired fallback.
        target = (WirelessRole.HOTSPOT if mode == HotspotMode.RECOVERY and not wired_ok
                  and s.dhcp_elapsed >= ETHERNET_DHCP_TIMEOUT else WirelessRole.OFF)
    elif config.wifi_configured and not wifi_exhausted:
        target = WirelessRole.CLIENT
    elif mode == HotspotMode.RECOVERY:
        target = WirelessRole.HOTSPOT
    else:
        target = WirelessRole.OFF

    if target == WirelessRole.HOTSPOT and not config.hotspot_credentials_valid:
        target = WirelessRole.OFF
    if (s.wireless == WirelessRole.HOTSPOT and not s.carrier and config.wifi_configured
            and mode == HotspotMode.RECOVERY and wifi_exhausted
            and s.retry_safe and s.retry_elapsed >= RETRY_DELAY):
        if s.hotspot_dhcp_running:
            return p(Action.STOP_HOTSPOT_DHCP, "stop DHCP before bounded client retry")
        return p(Action.RETRY_CLIENT, "safe recovery retry; stop AP before resetting client failure")
    if s.wireless == WirelessRole.HOTSPOT and target == WirelessRole.CLIENT:
        # Recovery stays available while an administrator is connected. Retry
        # failure state must be reset by actuator only after safe backoff.
        if not s.retry_safe or s.retry_elapsed < RETRY_DELAY:
            target = WirelessRole.HOTSPOT
    if s.wireless != target:
        if s.hotspot_dhcp_running:
            return p(Action.STOP_HOTSPOT_DHCP, "stop DHCP before role change")
        if s.wireless != WirelessRole.OFF:
            return p(Action.STOP_WIRELESS, "break before make: stop previous role")
        if target == WirelessRole.CLIENT:
            if s.carrier or s.wired != WiredRole.OFF:
                return p(Action.HOLD, "wired interlock")
            return p(Action.START_CLIENT, "no wired carrier; configured client")
        if target == WirelessRole.HOTSPOT:
            if not s.hotspot_isolated:
                return p(Action.INSTALL_HOTSPOT_ISOLATION, "isolation before radio")
            return p(Action.START_HOTSPOT, "isolated AP permitted")
    if (target == WirelessRole.HOTSPOT and s.wireless == target
            and s.hotspot_address and not s.hotspot_dhcp_running):
        return p(Action.START_HOTSPOT_DHCP, "verified active isolated AP only")
    return p(Action.HOLD, "desired role stable or waiting for observations")

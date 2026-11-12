"""Candidate wireless actuator. No live caller or mutating CLI.

The future root-owned service must hold an exclusive transition lock, verify
kernel gate contents and own all profiles. The injected gate and DHCP checks
are contracts, not independent enforcement by this module.
"""
import argparse
from dataclasses import asdict, dataclass
import ipaddress
import json
import time

from .network_actuator import IP, SafetyError, WiredActuator
from .network_gate import Gate
from .network_policy import HOTSPOT_ADDRESS, WirelessRole

CLIENT_NAME = "pi-player-wifi-client"
HOTSPOT_NAME = "pi-player-hotspot"
CLIENT_UUID = "0d8e74d2-a6c6-46bf-bab8-221456aa404b"
HOTSPOT_UUID = "df26c859-24bb-4324-8a4d-d8f374613389"
IW = "/usr/sbin/iw"


@dataclass(frozen=True)
class WirelessObservation:
    radio_enabled: bool
    device_state: int
    active_uuid: str | None
    role: WirelessRole | None
    ipv4_addresses: tuple[str, ...]
    default_route: bool


class WirelessActuator(WiredActuator):
    def __init__(self, *, gate_verified=lambda mode: False,
                 dhcp_stopped=lambda: False, sleep=time.sleep, **kwargs):
        super().__init__(**kwargs)
        self.gate_verified = gate_verified
        self.dhcp_stopped = dhcp_stopped
        self.sleep = sleep

    def observe_wireless(self):
        radio = self.nm("radio", "wifi")
        if radio not in ("enabled", "disabled"):
            raise SafetyError("Unknown Wi-Fi radio state")
        state = int(self.nm("-g", "GENERAL.STATE", "device", "show", "wlan0").split()[0])
        active = self.nm("-t", "-f", "UUID,DEVICE", "connection", "show", "--active")
        matches = [line.split(":", 1)[0] for line in active.splitlines() if line.endswith(":wlan0")]
        if len(matches) > 1:
            raise SafetyError("Multiple active wireless profiles")
        profile = matches[0] if matches else None
        role = {None: WirelessRole.OFF, CLIENT_UUID: WirelessRole.CLIENT,
                HOTSPOT_UUID: WirelessRole.HOTSPOT}.get(profile)
        data = json.loads(self.run(IP, "-j", "-4", "address", "show", "dev", "wlan0"))
        addresses = tuple(f'{a["local"]}/{a["prefixlen"]}'
                          for interface in data for a in interface.get("addr_info", [])
                          if a.get("family") == "inet" and a.get("scope") == "global")
        default = any(r.get("dst") == "default" and r.get("dev") == "wlan0"
                      for r in self.routes())
        return WirelessObservation(radio == "enabled", state, profile, role, addresses, default)

    def validate_profile(self, role):
        if role not in (WirelessRole.CLIENT, WirelessRole.HOTSPOT):
            raise SafetyError("Invalid wireless role")
        ap = role == WirelessRole.HOTSPOT
        profile = HOTSPOT_UUID if ap else CLIENT_UUID
        expected = {
            "connection.id": HOTSPOT_NAME if ap else CLIENT_NAME,
            "connection.type": "802-11-wireless",
            "connection.interface-name": "wlan0",
            "connection.autoconnect": "no",
            "802-11-wireless.mode": "ap" if ap else "infrastructure",
            "802-11-wireless-security.key-mgmt": "wpa-psk",
            "ipv6.method": "disabled",
        }
        if ap:
            expected.update({
                "802-11-wireless.band": "bg",
                "802-11-wireless.channel": "6",
                "802-11-wireless-security.proto": "rsn",
                "802-11-wireless-security.pairwise": "ccmp",
                "802-11-wireless-security.group": "ccmp",
                "ipv4.method": "manual",
                "ipv4.addresses": HOTSPOT_ADDRESS,
                "ipv4.never-default": "yes",
                "ipv4.gateway": "",
                "ipv4.dns": "",
            })
        for field, value in expected.items():
            if self.field(profile, field) != value:
                raise SafetyError("Managed wireless profile does not match policy: " + field)
        if ap:
            if self.field(profile, "802-11-wireless.ap-isolation") not in (
                    "1", "true", "yes", "1 (true)", "1 (yes)"):
                raise SafetyError("AP isolation is not explicitly enabled")
            if self.field(profile, "802-11-wireless-security.wps-method") not in (
                    "1", "disabled", "1 (disabled)", "0x1 (disabled)"):
                raise SafetyError("WPS is not explicitly disabled")
        elif self.field(profile, "ipv4.method") not in ("auto", "manual"):
            raise SafetyError("Client must use DHCP or static addressing, never shared mode")
        return profile

    def verify_owned_profiles(self):
        profiles = self.nm("-t", "-f", "UUID,TYPE", "connection", "show")
        for line in profiles.splitlines():
            profile, _, kind = line.partition(":")
            if kind not in ("wifi", "802-11-wireless"):
                continue
            if profile not in (CLIENT_UUID, HOTSPOT_UUID):
                raise SafetyError("Unmanaged wireless profile exists")
            if self.field(profile, "connection.autoconnect") != "no":
                raise SafetyError("Independent wireless autoconnect enabled")

    def assert_ready_to_start(self, role):
        gate = Gate.HOTSPOT if role == WirelessRole.HOTSPOT else Gate.CLIENT
        if self.gate_verified(gate) is not True or self.dhcp_stopped() is not True:
            raise SafetyError("Wireless gate or stopped hotspot DHCP not verified")
        self.verify_owned_profiles()
        wired = self.observe()
        wireless = self.observe_wireless()
        if wireless.active_uuid is not None or wireless.ipv4_addresses or wireless.default_route:
            raise SafetyError("Existing wireless connection must be stopped first")
        if type(wired.carrier) is not bool:
            raise SafetyError("Unknown Ethernet carrier")
        if role == WirelessRole.CLIENT:
            if wired.carrier or wired.active_uuid or wired.ipv4_addresses or wired.default_route:
                raise SafetyError("Ethernet client interlock closed")
        else:
            wanted = ipaddress.ip_network(HOTSPOT_ADDRESS, strict=False)
            for route in self.routes():
                dst = route.get("dst", "default")
                if dst != "default" and ipaddress.ip_network(dst, strict=False).overlaps(wanted):
                    raise SafetyError("Hotspot subnet overlaps existing route")

    def wait_ready(self):
        for _ in range(30):
            state = int(self.nm("-g", "GENERAL.STATE", "device", "show", "wlan0").split()[0])
            if state == 30:
                return
            self.sleep(1)
        raise SafetyError("Wireless device did not become available")

    def start(self, role, *, authorized=False):
        if authorized is not True:
            raise SafetyError("Wireless role not authorized")
        profile = self.validate_profile(role)
        self.assert_ready_to_start(role)
        # No unmanaged/autoconnect profile is allowed. No secret on argv.
        try:
            self.nm("radio", "wifi", "on")
            self.wait_ready()
            self.assert_ready_to_start(role)
            self.nm("--wait", "30", "connection", "up", "uuid", profile, "ifname", "wlan0")
            observed = self.observe_wireless()
            wired = self.observe()
            gate = Gate.HOTSPOT if role == WirelessRole.HOTSPOT else Gate.CLIENT
            if (observed.active_uuid != profile or observed.role != role
                    or observed.device_state != 100 or not observed.radio_enabled
                    or type(wired.carrier) is not bool
                    or self.gate_verified(gate) is not True
                    or self.dhcp_stopped() is not True):
                raise SafetyError("Wireless activation read-back failed")
            if role == WirelessRole.CLIENT:
                if wired.carrier or wired.active_uuid or wired.ipv4_addresses or wired.default_route:
                    raise SafetyError("Ethernet appeared during client activation")
                if not observed.ipv4_addresses:
                    raise SafetyError("Client has no IPv4 address")
            else:
                if observed.ipv4_addresses != (HOTSPOT_ADDRESS,) or observed.default_route:
                    raise SafetyError("Unexpected hotspot addressing")
                if not any(line.strip() == "type AP" for line in self.run(IW, "dev", "wlan0", "info").splitlines()):
                    raise SafetyError("Kernel does not report AP mode")
            return observed
        except Exception:
            # The caller retains the existing traffic gate and latches errors.
            self.nm("radio", "wifi", "off")
            raise

    def stop(self):
        if self.dhcp_stopped() is not True:
            raise SafetyError("Stop hotspot DHCP before switching wireless role")
        self.nm("radio", "wifi", "off")
        for _ in range(10):
            result = self.observe_wireless()
            if not (result.radio_enabled or result.active_uuid or result.ipv4_addresses or result.default_route):
                return result
            self.sleep(1)
        raise SafetyError("Wireless teardown not confirmed")


def main():
    parser = argparse.ArgumentParser(description="Read-only wireless inspection")
    parser.add_argument("--inspect", action="store_true", required=True)
    parser.parse_args()
    print(json.dumps(asdict(WirelessActuator().observe_wireless()), indent=2))


if __name__ == "__main__":
    main()

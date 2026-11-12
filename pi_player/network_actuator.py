"""Candidate wired actuator; not installed, enabled, or called by the API.

The only CLI is read-only inspection. Mutation methods are for a future
root-owned, locked controller with verified exclusive kernel gates.
"""
from dataclasses import dataclass
import argparse
import ipaddress
import json
import subprocess
import uuid
from pathlib import Path

from .network_policy import ETHERNET_FALLBACK, ETHERNET_DHCP_TIMEOUT

NM = "/usr/bin/nmcli"
IP = "/usr/sbin/ip"
FALLBACK_NAME = "pi-player-wired-fallback"
FALLBACK_UUID = "44998f91-67d5-4c55-9db7-91d183a71f42"


class SafetyError(RuntimeError):
    pass


@dataclass(frozen=True)
class WiredObservation:
    carrier: bool | None
    active_uuid: str | None
    ipv4_addresses: tuple[str, ...]
    default_route: bool
    wifi_disabled: bool


def read_carrier(path=Path("/sys/class/net/eth0/carrier")):
    try:
        return {"0": False, "1": True}.get(path.read_text().strip())
    except OSError:
        return None


class WiredActuator:
    def __init__(self, runner=subprocess.run, carrier_reader=read_carrier):
        self.runner = runner
        self.carrier_reader = carrier_reader

    def run(self, executable, *args):
        return self.runner([executable, *args], check=True, text=True,
                           capture_output=True, timeout=40,
                           env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LC_ALL": "C"}).stdout.strip()

    def nm(self, *args):
        return self.run(NM, *args)

    def field(self, profile, field):
        return self.nm("-g", field, "connection", "show", "uuid", profile)

    def routes(self):
        return json.loads(self.run(IP, "-j", "-4", "route", "show", "table", "all"))

    def observe(self):
        # UUID contains no escaped colon; the device name is a fixed literal.
        active = self.nm("-t", "-f", "UUID,DEVICE", "connection", "show", "--active")
        matches = [line.split(":", 1)[0] for line in active.splitlines()
                   if line.endswith(":eth0")]
        if len(matches) > 1:
            raise SafetyError("Multiple active wired profiles")
        data = json.loads(self.run(IP, "-j", "-4", "address", "show", "dev", "eth0"))
        addresses = tuple(f'{a["local"]}/{a["prefixlen"]}'
                          for interface in data for a in interface.get("addr_info", [])
                          if a.get("family") == "inet" and a.get("scope") == "global")
        default = any(r.get("dst") == "default" and r.get("dev") == "eth0"
                      for r in self.routes())
        return WiredObservation(self.carrier_reader(), matches[0] if matches else None,
                                addresses, default, self.nm("radio", "wifi") == "disabled")

    def validate_primary(self, profile):
        try:
            profile = str(uuid.UUID(profile))
        except (ValueError, TypeError, AttributeError) as exc:
            raise SafetyError("Invalid primary profile UUID") from exc
        if profile == FALLBACK_UUID:
            raise SafetyError("Primary UUID collides with fallback")
        expected = {"connection.type": "802-3-ethernet",
                    "connection.interface-name": "eth0",
                    "connection.autoconnect": "no",
                    "ipv4.method": "auto",
                    "ipv4.addresses": ""}
        for field, value in expected.items():
            if self.field(profile, field) != value:
                raise SafetyError("Primary profile not explicitly managed DHCP Ethernet")
        return profile

    def validate_fallback(self):
        expected = {"connection.id": FALLBACK_NAME,
                    "connection.type": "802-3-ethernet",
                    "connection.interface-name": "eth0",
                    "connection.autoconnect": "no",
                    "ipv4.method": "manual",
                    "ipv4.addresses": ETHERNET_FALLBACK,
                    "ipv4.never-default": "yes",
                    "ipv4.may-fail": "no",
                    "ipv4.dad-timeout": "3000",
                    "ipv4.gateway": "",
                    "ipv4.dns": "",
                    "ipv6.method": "disabled"}
        for field, value in expected.items():
            actual = self.field(FALLBACK_UUID, field)
            # nmcli may display the numeric DAD timeout with its unit.
            if field == "ipv4.dad-timeout":
                actual = actual.removesuffix(" ms")
            if actual != value:
                raise SafetyError("Unexpected fallback profile configuration")

    def assert_fallback_safe(self, primary):
        s = self.observe()
        if (s.carrier is not True or not s.wifi_disabled
                or s.active_uuid not in (None, primary)
                or s.ipv4_addresses or s.default_route):
            raise SafetyError("Wired fallback prerequisites not met")
        wanted = ipaddress.ip_network(ETHERNET_FALLBACK, strict=False)
        for route in self.routes():
            dst = route.get("dst", "default")
            if dst != "default" and ipaddress.ip_network(dst, strict=False).overlaps(wanted):
                raise SafetyError("Fallback subnet overlaps existing route")

    def start_fallback(self, primary, *, elapsed, verified_wired_gate=False):
        """Activate only after the future controller verifies gate and timeout.

        Never modify an existing primary profile. A failed activation removes
        the temporary fallback and raises; the controller must latch the error.
        """
        if verified_wired_gate is not True or elapsed < ETHERNET_DHCP_TIMEOUT:
            raise SafetyError("Wired gate or DHCP timeout not verified")
        primary = self.validate_primary(primary)
        self.assert_fallback_safe(primary)
        profiles = self.nm("-g", "UUID", "connection", "show").splitlines()
        if FALLBACK_UUID in profiles:
            raise SafetyError("Fallback UUID already exists; inspect before retry")
        created = False
        try:
            self.nm("connection", "add", "save", "no", "type", "ethernet",
                    "ifname", "eth0", "con-name", FALLBACK_NAME,
                    "connection.uuid", FALLBACK_UUID, "connection.autoconnect", "no",
                    "ipv4.method", "manual", "ipv4.addresses", ETHERNET_FALLBACK,
                    "ipv4.never-default", "yes", "ipv4.may-fail", "no",
                    "ipv4.dad-timeout", "3000", "ipv6.method", "disabled")
            created = True
            self.validate_fallback()
            self.assert_fallback_safe(primary)
            self.nm("--wait", "30", "connection", "up", "uuid", FALLBACK_UUID, "ifname", "eth0")
            s = self.observe()
            if (s.active_uuid != FALLBACK_UUID or s.ipv4_addresses != (ETHERNET_FALLBACK,)
                    or s.default_route or s.carrier is not True or not s.wifi_disabled):
                raise SafetyError("Fallback activation read-back failed")
            return s
        except Exception:
            if created:
                self.nm("connection", "delete", "uuid", FALLBACK_UUID)
            raise

    def restore_primary(self, primary, *, verified_wired_gate=False, retry_safe=False):
        """Elective retry only after a verified no-session decision."""
        if verified_wired_gate is not True or retry_safe is not True:
            raise SafetyError("Wired gate or safe retry not verified")
        primary = self.validate_primary(primary)
        self.validate_fallback()
        s = self.observe()
        if (s.carrier is not True or not s.wifi_disabled or s.active_uuid != FALLBACK_UUID
                or s.ipv4_addresses != (ETHERNET_FALLBACK,) or s.default_route):
            raise SafetyError("Fallback not active or unsafe to restore")
        # Retain the owned fallback profile until primary DHCP is verified.
        try:
            self.nm("--wait", "30", "connection", "up", "uuid", primary, "ifname", "eth0")
            s = self.observe()
            if (s.active_uuid != primary or not s.ipv4_addresses
                    or s.carrier is not True or not s.wifi_disabled):
                raise SafetyError("Primary DHCP retry unsuccessful")
        except Exception as exc:
            # Recover fallback only if no new IPv4 or foreign profile appeared.
            s = self.observe()
            if (s.carrier is True and s.wifi_disabled
                    and s.active_uuid in (None, primary) and not s.ipv4_addresses
                    and not s.default_route):
                self.assert_fallback_safe(primary)
                self.nm("--wait", "30", "connection", "up", "uuid", FALLBACK_UUID, "ifname", "eth0")
                restored = self.observe()
                if (restored.active_uuid != FALLBACK_UUID
                        or restored.ipv4_addresses != (ETHERNET_FALLBACK,)
                        or restored.default_route or restored.carrier is not True
                        or not restored.wifi_disabled):
                    raise SafetyError("Fallback restoration read-back failed") from exc
            raise SafetyError("Primary DHCP retry failed; reobserve before further action") from exc
        self.nm("connection", "delete", "uuid", FALLBACK_UUID)
        return s


def main():
    from dataclasses import asdict
    parser = argparse.ArgumentParser(description="Read-only wired network inspection")
    parser.add_argument("--inspect", action="store_true", required=True)
    parser.parse_args()
    print(json.dumps(asdict(WiredActuator().observe()), indent=2))


if __name__ == "__main__":
    main()

"""Candidate dedicated hotspot DHCP lifecycle. No service is installed here.

Only --render-config is exposed as a CLI. The future root-owned controller
must hold the transition lock and provide an independent gate verifier.
"""
import argparse
from dataclasses import dataclass
from pathlib import Path

from .network_actuator import SafetyError
from .network_gate import Gate, render_hotspot_dhcp
from .network_policy import HOTSPOT_ADDRESS, WirelessRole
from .network_wireless import HOTSPOT_UUID, IW, WirelessActuator

UNIT = "pi-player-hotspot-dhcp.service"
SYSTEMCTL = "/usr/bin/systemctl"
DNSMASQ = "/usr/sbin/dnsmasq"
CONFIG_PATH = "/etc/pi-player/network/hotspot-dhcp.conf"
RUNTIME_DIR = "/run/pi-player-hotspot-dhcp"


def render_service_config():
    return (
        render_hotspot_dhcp()
        + "except-interface=eth0\n"
        + "no-dhcp-interface=eth0\n"
        + "user=nobody\n"
        + "group=nogroup\n"
        + f"dhcp-leasefile={RUNTIME_DIR}/leases/dhcp.leases\n"
        + f"pid-file={RUNTIME_DIR}/dnsmasq.pid\n"
    )


def host_isolation_ready():
    """Conservative host preflight; not a substitute for nft read-back."""
    try:
        return (
            Path("/proc/sys/net/ipv4/ip_forward").read_text().strip() == "0"
            and Path("/proc/sys/net/ipv6/conf/all/forwarding").read_text().strip() == "0"
            and all(Path("/sys/class/net", iface).is_dir()
                    and not Path("/sys/class/net", iface, "master").is_symlink()
                    for iface in ("eth0", "wlan0"))
        )
    except OSError:
        return False


@dataclass(frozen=True)
class ServiceState:
    load: str
    active: str
    sub: str
    main_pid: int
    control_pid: int
    job: str

    @property
    def running(self):
        return self.load == "loaded" and self.active == "active" and self.sub == "running" and self.main_pid > 0

    @property
    def stopped(self):
        return (
            self.load in ("loaded", "not-found")
            and self.active in ("inactive", "failed")
            and self.main_pid == 0 and self.control_pid == 0
            and self.job in ("", "0")
        )


class HotspotDHCP:
    def __init__(self, *, wireless=None, gate_verified=lambda mode: False,
                 host_ready=host_isolation_ready):
        self.wireless = wireless if wireless is not None else WirelessActuator()
        self.gate_verified = gate_verified
        self.host_ready = host_ready

    def status(self):
        raw = self.wireless.run(SYSTEMCTL, "show", UNIT,
                                "--property=LoadState,ActiveState,SubState,MainPID,ControlPID,Job")
        fields = dict(line.split("=", 1) for line in raw.splitlines() if "=" in line)
        try:
            return ServiceState(fields["LoadState"], fields["ActiveState"],
                                fields["SubState"], int(fields["MainPID"]),
                                int(fields["ControlPID"]), fields["Job"])
        except (KeyError, ValueError) as exc:
            raise SafetyError("Hotspot DHCP service state incomplete") from exc

    def stopped(self):
        return self.status().stopped

    def assert_safe(self):
        if self.gate_verified(Gate.HOTSPOT) is not True or self.host_ready() is not True:
            raise SafetyError("Hotspot isolation not verified")
        s = self.wireless.observe_wireless()
        if (not s.radio_enabled or s.device_state != 100
                or s.active_uuid != HOTSPOT_UUID or s.role != WirelessRole.HOTSPOT
                or s.ipv4_addresses != (HOTSPOT_ADDRESS,) or s.default_route):
            raise SafetyError("Verified active hotspot required for DHCP")
        if type(self.wireless.observe().carrier) is not bool:
            raise SafetyError("Unknown Ethernet carrier")
        self.wireless.validate_profile(WirelessRole.HOTSPOT)
        self.wireless.verify_owned_profiles()
        info = self.wireless.run(IW, "dev", "wlan0", "info")
        if not any(line.strip() == "type AP" for line in info.splitlines()):
            raise SafetyError("Kernel does not report AP mode")

    def start(self, *, authorized=False):
        if authorized is not True:
            raise SafetyError("Hotspot DHCP not authorized")
        state = self.status()
        if not (state.running or state.stopped) or state.load != "loaded":
            raise SafetyError("Dedicated DHCP unit unavailable or transitioning")
        if state.running:
            self.reconcile()
            return self.status()
        self.assert_safe()
        # Unit and config are future root-owned installed files. Never run a
        # config in the application-owned checkout as a privileged service.
        self.wireless.run(DNSMASQ, "--test", f"--conf-file={CONFIG_PATH}")
        self.assert_safe()
        try:
            self.wireless.run(SYSTEMCTL, "start", UNIT)
            self.assert_safe()
            state = self.status()
            if not state.running:
                raise SafetyError("Dedicated DHCP service did not become active")
            return state
        except Exception:
            self.stop()
            raise

    def stop(self):
        self.wireless.run(SYSTEMCTL, "stop", UNIT)
        state = self.status()
        if not state.stopped:
            raise SafetyError("Hotspot DHCP shutdown not confirmed")
        return state

    def reconcile(self):
        """Future controller calls this before role changes and on observation."""
        try:
            state = self.status()
            if state.stopped:
                return state
            if not state.running:
                raise SafetyError("Unexpected DHCP service transition")
            self.assert_safe()
            return state
        except Exception:
            # Unknown AP/gate/service state must not authorize continued DHCP.
            self.stop()
            raise


def main():
    parser = argparse.ArgumentParser(description="Render candidate DHCP configuration only")
    parser.add_argument("--render-config", action="store_true", required=True)
    parser.parse_args()
    print(render_service_config(), end="")


if __name__ == "__main__":
    main()

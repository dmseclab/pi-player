"""Candidate kernel traffic gates for the Pi Player network actuator.

This module is intentionally not called by install/update or a running service.
The lab must check nft syntax and packet behaviour before any live integration.
No user-supplied interface names, commands or nft expressions are accepted.
"""
from enum import Enum
import subprocess


class Gate(str, Enum):
    CLOSED = "closed"
    WIRED = "wired"
    CLIENT = "client"
    HOTSPOT = "hotspot"


NETDEV_TABLE = "pi_player_uplink_gate"
INET_TABLE = "pi_player_ap_gate"


def render_gate(mode: Gate) -> str:
    """Replace both owned tables in one nft transaction.

    netdev ingress/egress drops entire Ethernet frames, including ARP and IPv6,
    on the nonselected uplink. This is distinct from disabling an IP route.
    HOTSPOT allows Ethernet plus the restricted AP test service only.
    The real application port is intentionally NOT allowed.
    """
    mode = Gate(mode)
    blocked = {
        Gate.CLOSED: ("eth0", "wlan0"),
        Gate.WIRED: ("wlan0",),
        Gate.CLIENT: ("eth0",),
        Gate.HOTSPOT: (),
    }[mode]
    lines = [
        "destroy table netdev " + NETDEV_TABLE,
        "destroy table inet " + INET_TABLE,
        "table netdev " + NETDEV_TABLE + " {",
    ]
    for iface in ("eth0", "wlan0"):
        for direction in ("ingress", "egress"):
            policy = "drop" if iface in blocked else "accept"
            lines.extend([
                f"    chain {iface}_{direction} {{",
                f'        type filter hook {direction} device "{iface}" priority -500;',
                f"        policy {policy};",
                "        counter",
                "    }",
            ])
    lines.append("}")
    # Always deny forwarding on either managed interface, even if an unrelated
    # service enables forwarding. This does not replace bridge/namespace checks.
    lines.extend([
        "table inet " + INET_TABLE + " {",
        "    chain forward {",
        "        type filter hook forward priority -10; policy accept;",
        '        iifname { "eth0", "wlan0" } counter drop',
        '        oifname { "eth0", "wlan0" } counter drop',
        "    }",
    ])
    if mode == Gate.HOTSPOT:
        lines.extend([
            "    chain input {",
            "        type filter hook input priority -10; policy accept;",
            '        iifname "wlan0" ip protocol udp udp sport 68 udp dport 67 counter accept',
            '        iifname "wlan0" ip saddr 10.42.0.0/24 ip daddr 10.42.0.1 tcp dport 18000 counter accept',
            '        iifname "wlan0" counter drop',
            "    }",
            "    chain output {",
            "        type filter hook output priority -10; policy accept;",
            '        oifname "wlan0" ip protocol udp udp sport 67 udp dport 68 counter accept',
            '        oifname "wlan0" ip saddr 10.42.0.1 ip daddr 10.42.0.0/24 tcp sport 18000 ct state established counter accept',
            '        oifname "wlan0" counter drop',
            "    }",
        ])
    lines.extend(["}", ""])
    return "\n".join(lines)


def check_gate(mode: Gate, runner=subprocess.run) -> None:
    """Syntax/kernel compatibility check; never installs the rules."""
    runner(
        ["/usr/sbin/nft", "-c", "-f", "-"],
        input=render_gate(mode), text=True, check=True,
        capture_output=True, timeout=15,
    )


def replace_gate(mode: Gate, runner=subprocess.run) -> None:
    """Candidate privileged primitive, NOT wired into the application.

    Call only from a trusted root-owned actuator holding its transition lock,
    with independent profile autoconnect disabled. A successful atomic nft
    transaction is not a complete live enforcement or read-back verification.
    """
    check_gate(mode, runner)
    runner(
        ["/usr/sbin/nft", "-f", "-"],
        input=render_gate(mode), text=True, check=True,
        capture_output=True, timeout=15,
    )


def render_hotspot_dhcp() -> str:
    """Restricted DHCP only, using the dedicated hotspot interface."""
    return (
        "port=0\n"
        "interface=wlan0\n"
        "bind-interfaces\n"
        "dhcp-range=10.42.0.2,10.42.0.3,255.255.255.0,1h\n"
        "dhcp-lease-max=2\n"
        "dhcp-option=option:router\n"
        "dhcp-option=option:dns-server\n"
    )

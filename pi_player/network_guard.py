"""Candidate DHCP pre-start guard. Not installed or enabled.

Must run from a trusted root-owned package and a root-owned service unit.
This checks actual firewall and AP/config state, not a controller flag.
"""
import os
import sys

from .network_dhcp import HotspotDHCP
from .network_gate_verify import verify_gate


def guard(*, uid=os.geteuid, factory=HotspotDHCP, verifier=verify_gate):
    if uid() != 0:
        return False
    try:
        factory(gate_verified=verifier).assert_safe()
        return True
    except Exception:
        # Deliberately avoid logging exceptions which might expose settings.
        return False


def main():
    if guard():
        return 0
    print("Hotspot DHCP pre-start safety checks failed", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

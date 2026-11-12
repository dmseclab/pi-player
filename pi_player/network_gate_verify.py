"""Conservative independent nftables read-back verification.

Reject anything except the exact expected owned ruleset. The appliance must
not have competing firewall managers, bridge/NAT/flowtable rules, or other
nftables tables. This is deliberately strict; an unknown nft output format
fails closed rather than approximating rule equivalence.
"""
import argparse
import subprocess
import sys

from .network_gate import Gate, render_gate

NFT = "/usr/sbin/nft"


def canonical_lines(text):
    # Compare rule boundaries and order, not a bag of tokens. nft -s omits
    # counters and -y renders numeric priorities. Only formatting is ignored.
    return tuple(" ".join(line.split()) for line in text.splitlines() if line.strip())


def expected_ruleset(mode):
    return "\n".join(line for line in render_gate(Gate(mode)).splitlines()
                     if not line.startswith("destroy table ")) + "\n"


def matches_ruleset(mode, observed):
    if not isinstance(observed, str):
        return False
    return canonical_lines(observed) == canonical_lines(expected_ruleset(mode))


def verify_gate(mode, runner=subprocess.run):
    """Read actual kernel rules once; never apply or repair them here."""
    try:
        mode = Gate(mode)
        result = runner([NFT, "-s", "-y", "list", "ruleset"],
                        check=True, capture_output=True, text=True, timeout=10,
                        env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LC_ALL": "C"})
        return matches_ruleset(mode, result.stdout)
    except (OSError, subprocess.SubprocessError, ValueError):
        return False


def main():
    parser = argparse.ArgumentParser(description="Verify firewall ruleset (read only)")
    parser.add_argument("mode", choices=[mode.value for mode in Gate])
    parser.add_argument("--stdin", action="store_true",
                        help="Compare a supplied snapshot instead of reading kernel rules")
    args = parser.parse_args()
    passed = matches_ruleset(args.mode, sys.stdin.read()) if args.stdin else verify_gate(args.mode)
    print("PASS: exact gate read-back" if passed else "FAIL: ruleset differs or unavailable")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

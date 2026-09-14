from __future__ import annotations

import argparse
import json
import sys

from .health import integrity_report


def main() -> int:
    parser = argparse.ArgumentParser(description="Check Pi Player persistent asset integrity")
    parser.add_argument("--checksum", action="store_true", help="also verify SHA-256 checksums")
    args = parser.parse_args()
    report = integrity_report(verify_checksums=args.checksum)
    print(json.dumps(report, indent=2))
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    sys.exit(main())

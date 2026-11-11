#!/usr/bin/env python3
"""Read-only source and Git-history secret preflight; findings redact matched values.

This is heuristic, not a replacement for Gitleaks or GitHub secret scanning.
Run inside a Git checkout with: python3 deploy/repo-preflight.py
"""
from __future__ import annotations

import re
import subprocess
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAX_BLOB = 8 * 1024 * 1024
PATTERNS = {
    "private-key": re.compile(rb"-----BEGIN (?:RSA |OPENSSH |EC |DSA )?PRIVATE KEY-----"),
    "credential-token": re.compile(rb"\b(?:ghp_|gho_|ghu_|ghs_|github_pat_|glpat-|sk-proj-|sk_live_|AKIA)[A-Za-z0-9_-]{8,}"),
    "authorization-header": re.compile(rb"(?i)\bAuthorization\s*[:=]\s*[\"']?(?:Bearer|Basic)\s+[A-Za-z0-9._/+={}-]{16,}"),
    "embedded-url-credentials": re.compile(rb"(?i)https?://[^\s/@:]+:[^\s/@]+@[^/\s]+"),
}
PRIVATE_IP = re.compile(rb"\b(?:10\.(?:\d{1,3}\.){2}\d{1,3}|192\.168\.\d{1,3}\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})\b")
SUSPECT_NAME = re.compile(r"(?i)(?:^|/)(?:\.env(?:\..+)?|id_(?:rsa|ed25519)|.*\.(?:p12|pfx|pem|key|sqlite3?|db|log))$")


def git(*args: str) -> bytes:
    return subprocess.check_output(["git", "-C", str(ROOT), *args], stderr=subprocess.DEVNULL)


def detect(data: bytes, where: str, findings: set[tuple[str, str, int]]) -> None:
    for kind, pattern in PATTERNS.items():
        for match in pattern.finditer(data):
            findings.add((where, kind, data.count(b"\n", 0, match.start()) + 1))
    for match in PRIVATE_IP.finditer(data):
        findings.add((where, "private-ip-review", data.count(b"\n", 0, match.start()) + 1))


def main() -> int:
    findings: set[tuple[str, str, int]] = set()
    names = git("ls-files", "-z").decode("utf-8", "replace").split("\0")
    checked = 0
    for path in filter(None, names):
        candidate = ROOT / path
        if not candidate.is_file():
            continue
        if SUSPECT_NAME.search(path):
            findings.add((path, "sensitive-filename-review", 0))
        if candidate.stat().st_size <= MAX_BLOB:
            detect(candidate.read_bytes(), path, findings)
            checked += 1

    objects = git("rev-list", "--objects", "--all").decode("utf-8", "replace").splitlines()
    blob_paths: dict[str, str] = {}
    for entry in objects:
        oid, _, path = entry.partition(" ")
        if path and oid not in blob_paths:
            blob_paths[oid] = path
    scanned_blobs = 0
    skipped = 0
    process = subprocess.Popen(
        ["git", "-C", str(ROOT), "cat-file", "--batch"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
    )
    assert process.stdin is not None and process.stdout is not None
    for oid, path in blob_paths.items():
        process.stdin.write((oid + "\n").encode())
        process.stdin.flush()
        header = process.stdout.readline().decode("ascii", "replace").strip().split()
        if len(header) != 3:
            raise RuntimeError("Unexpected git cat-file response")
        _, kind, size = header
        size = int(size)
        if kind == "blob" and size <= MAX_BLOB:
            data = process.stdout.read(size)
            detect(data, "history:" + path, findings)
            scanned_blobs += 1
        else:
            process.stdout.read(size)
            skipped += 1
        process.stdout.read(1)  # trailing newline
    process.stdin.close()
    process.wait()
    log_messages = git("log", "--all", "--format=%B").strip()
    detect(log_messages, "history:commit-messages", findings)

    print("PI PLAYER REPOSITORY PREFLIGHT — READ ONLY / REDACTED")
    print(f"Tracked files checked: {checked}; historical Git blobs: {scanned_blobs}; skipped oversized/nonblob: {skipped}")
    print("Finding totals:", dict(Counter(kind for _, kind, _ in findings)))
    for path, kind, line in sorted(findings)[:100]:
        print(f"  {kind}: {path}" + (f":{line}" if line else ""))
    if len(findings) > 100:
        print(f"  ... {len(findings) - 100} additional locations omitted")
    print("No credential values are printed. Heuristic scan cannot guarantee absence of secrets.")
    high_risk = {"private-key", "credential-token", "authorization-header", "embedded-url-credentials"}
    return 2 if any(kind in high_risk for _, kind, _ in findings) else 0


if __name__ == "__main__":
    raise SystemExit(main())

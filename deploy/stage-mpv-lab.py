#!/usr/bin/env python3
"""Reversible STAGING ONLY of the opt-in MPV broker systemd unit.

The default is a dry run; --stage requires the lab hostname and root. No
service gets enabled or started, no users are created, and Chromium is not
modified. Rollback removes ONLY the identical staged file from the manifest.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path

UNIT_NAME = "pi-player-mpv-broker.service"
DEFAULT_SYSTEMD = Path("/etc/systemd/system")
DEFAULT_STATE = Path("/var/backups/pi-player/mpv-lab-stage")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def planned(source: Path, target: Path, state: Path) -> dict:
    return {"source": str(source), "target": str(target),
            "state": str(state), "target_exists": target.exists(),
            "state_exists": state.exists(), "will_enable": False,
            "will_start": False, "changes_existing_player": False}


def stage(source: Path, target: Path, state: Path, *, hostname: str,
          effective_uid: int, run=subprocess.run) -> None:
    if hostname != "pi-player" or effective_uid != 0:
        raise RuntimeError("Staging permitted only as root on lab pi-player")
    if target.name != UNIT_NAME or state.exists() or target.exists():
        raise RuntimeError("Refusing to overwrite existing installation or stage")
    if not source.is_file() or source.is_symlink():
        raise RuntimeError("Untrusted staging source")
    contents = source.read_bytes()
    if b"[Service]" not in contents or b"User=pi-player-broker" not in contents:
        raise RuntimeError("Invalid isolated broker unit")
    # Stage directory must not be previously occupied or linked.
    state.mkdir(mode=0o700, parents=False, exist_ok=False)
    created = False
    try:
        target.write_bytes(contents)
        target.chmod(0o644)
        created = True
        manifest = {"target": str(target), "sha256": digest(target),
                    "hostname": hostname, "service_enabled": False}
        (state / "manifest.json").write_text(json.dumps(manifest, sort_keys=True))
        (state / "manifest.json").chmod(0o600)
        # A daemon-reload does not start or enable the service.
        run(["systemctl", "daemon-reload"], check=True)
    except BaseException:
        if created:
            target.unlink(missing_ok=True)
        if state.exists():
            for child in state.iterdir():
                child.unlink()
            state.rmdir()
        raise


def rollback(target: Path, state: Path, *, hostname: str,
             effective_uid: int, run=subprocess.run) -> None:
    if hostname != "pi-player" or effective_uid != 0:
        raise RuntimeError("Rollback permitted only as root on lab pi-player")
    if not state.is_dir() or state.is_symlink():
        raise RuntimeError("No trusted lab stage manifest")
    manifest_file = state / "manifest.json"
    info = json.loads(manifest_file.read_text())
    if (target.name != UNIT_NAME or info.get("target") != str(target)
            or info.get("hostname") != hostname or not target.is_file()
            or target.is_symlink() or info.get("sha256") != digest(target)):
        raise RuntimeError("Stage differs from manifest; manual review required")
    result = run(["systemctl", "is-active", "--quiet", UNIT_NAME], check=False)
    if result.returncode == 0:
        raise RuntimeError("Refusing rollback while broker is running")
    result = run(["systemctl", "is-enabled", "--quiet", UNIT_NAME], check=False)
    if result.returncode == 0:
        raise RuntimeError("Refusing rollback of enabled unit")
    target.unlink()
    manifest_file.unlink()
    state.rmdir()
    run(["systemctl", "daemon-reload"], check=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    op = parser.add_mutually_exclusive_group()
    op.add_argument("--stage", action="store_true")
    op.add_argument("--rollback", action="store_true")
    p = parser.parse_args(argv)
    source = Path(__file__).resolve().with_name("pi-player-mpv-broker.lab.service")
    target = DEFAULT_SYSTEMD / UNIT_NAME
    state = DEFAULT_STATE
    if p.stage:
        stage(source, target, state, hostname=socket.gethostname(),
              effective_uid=os.geteuid())
    elif p.rollback:
        rollback(target, state, hostname=socket.gethostname(),
                 effective_uid=os.geteuid())
    else:
        print(json.dumps(planned(source, target, state), indent=2))


if __name__ == "__main__":
    main()

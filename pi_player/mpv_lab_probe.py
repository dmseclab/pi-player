"""Read-only host probe for a *future* Pi Player hybrid laboratory trial.

This never changes service state, filesystem permissions, user accounts,
playlists, playback or the Wayland compositor. Unknown facts remain unknown.
Run manually on a lab host only after an operator authorizes inspection.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path


def _read(path: Path, *, limit: int = 16384) -> str | None:
    try:
        if not path.is_file():
            return None
        with path.open("rb") as stream:
            data = stream.read(limit + 1)
        if len(data) > limit:
            return None
        return data.decode("utf-8")
    except (OSError, UnicodeError):
        return None


def _unit_user(text: str | None) -> str | None:
    if not text:
        return None
    result = None
    in_service = False
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("[") and line.endswith("]"):
            in_service = line == "[Service]"
        elif in_service and line.startswith("User="):
            result = line.partition("=")[2].strip() or None
    return result


def _run(args: tuple[str, ...]) -> str | None:
    try:
        result = subprocess.run(args, capture_output=True, text=True,
                                timeout=3, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def inspect(*, api_unit: Path, kiosk_unit: Path,
            cgroup_controllers: Path = Path("/sys/fs/cgroup/cgroup.controllers"),
            compositor_socket_dir: Path | None = None) -> dict:
    """Collect evidence only; even all green is NOT an enable instruction."""
    api = _unit_user(_read(api_unit))
    kiosk = _unit_user(_read(kiosk_unit))
    # Source/installed service unit declaration is not proof of the effective
    # running identity; a later deployment must verify the process UID too.
    try:
        import pwd
        api_uid = pwd.getpwnam(api).pw_uid if api else None
        kiosk_uid = pwd.getpwnam(kiosk).pw_uid if kiosk else None
    except (KeyError, OSError):
        api_uid = kiosk_uid = None
    controllers = _read(cgroup_controllers)
    runtime = compositor_socket_dir
    if runtime is None:
        runtime_value = os.environ.get("XDG_RUNTIME_DIR", "")
        runtime = Path(runtime_value) if runtime_value.startswith("/") else None
    wayland = False
    if runtime:
        try:
            wayland = runtime.is_dir() and any(
                p.name.startswith("wayland-") and p.is_socket()
                for p in runtime.iterdir()
            )
        except OSError:
            wayland = False
    result = {
        "host": _run(("hostname",)) or "unknown",
        "kernel": _run(("uname", "-r")) or "unknown",
        "api_declared_account": api,
        "kiosk_declared_account": kiosk,
        "api_uid": api_uid,
        "kiosk_uid": kiosk_uid,
        "accounts_separated": (api_uid is not None and kiosk_uid is not None
                               and api_uid != kiosk_uid),
        "cgroup_v2_controllers_present": controllers is not None,
        "wayland_socket_observed": bool(wayland),
        "mpv_binary_found": bool(shutil.which("mpv")),
        "chromium_binary_found": bool(shutil.which("chromium")
                                      or shutil.which("chromium-browser")),
        "hybrid_activation_supported": False,
        "read_only": True,
    }
    result["blockers"] = [
        name for name, present in (
            ("account_separation", result["accounts_separated"]),
            ("cgroup_v2", result["cgroup_v2_controllers_present"]),
            ("wayland_socket", result["wayland_socket_observed"]),
            ("mpv", result["mpv_binary_found"]),
            ("chromium_fallback", result["chromium_binary_found"]),
        ) if not present
    ]
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-unit", type=Path,
                        default=Path("/etc/systemd/system/pi-player-api.service"))
    parser.add_argument("--kiosk-unit", type=Path,
                        default=Path("/etc/systemd/system/pi-player-kiosk.service"))
    args = parser.parse_args(argv)
    report = inspect(api_unit=args.api_unit, kiosk_unit=args.kiosk_unit)
    print(json.dumps(report, sort_keys=True, indent=2))
    return 0  # An inspection result is not a command to change anything.


if __name__ == "__main__":
    raise SystemExit(main())

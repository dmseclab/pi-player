#!/usr/bin/env python3
"""Conservative Chromium GPU resource watchdog.

Called once per minute by pi-player-watchdog.sh as root. Stdlib only.
Writes diagnostic samples to the system journal via stdout and persistent state
under /var/lib/pi-player; does not directly terminate processes.
Exit 10: request one rate-limited kiosk restart. All other exits: observe only.
"""
import json
import os
import time
from pathlib import Path

STATE = Path("/var/lib/pi-player/gpu-watchdog-state.json")
BOOT_ID = Path("/proc/sys/kernel/random/boot_id")
THRESHOLD = 1000
CONSECUTIVE = 3
COOLDOWN_SECONDS = 6 * 3600
MAX_DAILY_RESTARTS = 2


def gpu_samples(proc=Path("/proc")):
    found = []
    for path in proc.iterdir():
        if not path.name.isdecimal():
            continue
        try:
            raw = (path / "cmdline").read_bytes().replace(b"\0", b" ")
            if b"chromium" not in raw or b"--type=gpu-process" not in raw:
                continue
            fd = path / "fd"
            total = 0
            shared = 0
            for entry in fd.iterdir():
                try:
                    target = os.readlink(entry)
                except OSError:
                    continue
                total += 1
                if target.startswith("/dev/shm/.org.chromium."):
                    shared += 1
            found.append({"pid": int(path.name), "fds": total, "chromium_shm": shared})
        except (OSError, ValueError):
            continue
    return found


def blocked_tasks(proc=Path("/proc")):
    """Never restart the kiosk if the kernel already has blocked D-state tasks."""
    found = []
    for path in proc.iterdir():
        if not path.name.isdecimal():
            continue
        try:
            stat = (path / "stat").read_text()
            state = stat.rsplit(")", 1)[1].strip().split()[0]
            if state == "D":
                found.append(int(path.name))
        except (OSError, IndexError):
            continue
    return found


def next_state(prior, samples, blocked, now, boot):
    if prior.get("boot_id") != boot:
        prior = {"boot_id": boot, "high_samples": 0, "recoveries": []}
    history = [t for t in prior.get("recoveries", []) if now - t < 86400 and t <= now]
    high = bool(samples) and any(s["chromium_shm"] >= THRESHOLD for s in samples)
    high_samples = prior.get("high_samples", 0) + 1 if high else 0
    last = history[-1] if history else 0
    ready = high_samples >= CONSECUTIVE and not blocked and len(history) < MAX_DAILY_RESTARTS and now - last >= COOLDOWN_SECONDS
    if ready:
        history.append(now)
        high_samples = 0
    return {"boot_id": boot, "high_samples": high_samples, "recoveries": history}, ready


def main():
    now = int(time.time())
    boot = BOOT_ID.read_text().strip()
    samples = gpu_samples()
    blocked = blocked_tasks()
    try:
        previous = json.loads(STATE.read_text())
    except (OSError, ValueError):
        previous = {}
    updated, recover = next_state(previous, samples, blocked, now, boot)
    STATE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(updated) + "\n")
    os.chmod(tmp, 0o600)
    tmp.replace(STATE)
    print(json.dumps({"event": "gpu_watchdog", "time": now, "gpu": samples, "blocked_tasks": blocked,
                      "high_samples": updated["high_samples"], "recover": recover}), flush=True)
    return 10 if recover else 0


if __name__ == "__main__":
    raise SystemExit(main())

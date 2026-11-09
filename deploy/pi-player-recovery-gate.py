#!/usr/bin/env python3
"""Shared, fail-closed recovery permission gate for Pi Player watchdog actions.

Usage: python3 recovery-gate.py kiosk|api
Exit 0: recovery authorized and recorded; exit 1: suppressed.
No subprocess/service restarts occur here. Requires root via existing watchdog.
"""
import json
import os
import sys
import time
from pathlib import Path

STATE = Path("/var/lib/pi-player/recovery-gate-state.json")
DAY = 24 * 3600
POLICIES = {
    "kiosk": {"cooldown": 15 * 60, "max_day": 3},
    "api": {"cooldown": 15 * 60, "max_day": 3},
}


def validate_state(state):
    """Reject malformed persistent history instead of resetting recovery limits."""
    if not isinstance(state, dict):
        raise ValueError("state must be an object")
    if set(state) - {"history"}:
        raise ValueError("unknown recovery state fields")
    history = state.get("history", {})
    if not isinstance(history, dict):
        raise ValueError("history must be an object")
    for kind, timestamps in history.items():
        if kind not in POLICIES or not isinstance(timestamps, list):
            raise ValueError("invalid recovery history entry")
        if any(type(t) is not int or t < 0 for t in timestamps):
            raise ValueError("invalid recovery timestamp")


def allowed(state, kind, now, blocked):
    validate_state(state)
    if kind not in POLICIES:
        return False, state, "unknown recovery kind"
    history = state.get("history", {})
    # Shared cooldown across all kinds prevents combined restart storms.
    all_recent = sorted(
        t for events in history.values() for t in events if 0 <= now - t < DAY
    )
    policy = POLICIES[kind]
    own_recent = [t for t in history.get(kind, []) if 0 <= now - t < DAY]
    if blocked:
        return False, state, "kernel D-state task detected"
    if all_recent and now - all_recent[-1] < policy["cooldown"]:
        return False, state, "shared recovery cooldown"
    if len(own_recent) >= policy["max_day"]:
        return False, state, "daily recovery limit"
    next_history = {
        k: [t for t in values if 0 <= now - t < DAY]
        for k, values in history.items()
    }
    next_history.setdefault(kind, []).append(now)
    return True, {"history": next_history}, "approved"


def blocked_tasks(proc=Path("/proc")):
    for path in proc.iterdir():
        if not path.name.isdecimal():
            continue
        try:
            state = (path / "stat").read_text().rsplit(")", 1)[1].strip().split()[0]
            if state == "D":
                return True
        except (OSError, IndexError):
            continue
    return False


def main(kind):
    now = int(time.time())
    try:
        prior = json.loads(STATE.read_text())
    except FileNotFoundError:
        prior = {}
    except (OSError, ValueError) as error:
        print(f"recovery gate: state read error: {error}", flush=True)
        return 1  # never reset lost/corrupt state and accidentally permit storm

    try:
        validate_state(prior)
        authorize, updated, message = allowed(prior, kind, now, blocked_tasks())
    except (ValueError, TypeError, OSError) as error:
        print(f"recovery gate: validation or kernel inspection error: {error}", flush=True)
        return 1
    if authorize:
        try:
            STATE.parent.mkdir(parents=True, exist_ok=True)
            temp = STATE.with_suffix(".tmp")
            temp.write_text(json.dumps(updated) + "\n")
            os.chmod(temp, 0o600)
            temp.replace(STATE)
        except OSError as error:
            print(f"recovery gate: state write error: {error}", flush=True)
            return 1
    print(f"recovery gate: {kind} {message}", flush=True)
    return 0 if authorize else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) == 2 else ""))

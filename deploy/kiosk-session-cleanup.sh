#!/usr/bin/env bash
# Called by systemd after the dedicated tty1 kiosk session stops.
# The pi-player account is exclusive to the display; do not touch any
# interactive administrator's Chromium processes.
set -euo pipefail
user=pi-player
id "$user" >/dev/null 2>&1 || exit 0
if pgrep -u "$user" -x chromium >/dev/null 2>&1; then
  pkill -TERM -u "$user" -x chromium || true
  for _ in 1 2 3 4 5; do
    pgrep -u "$user" -x chromium >/dev/null 2>&1 || exit 0
    sleep 1
  done
  # Only the appliance's dedicated kiosk account is affected.
  pkill -KILL -u "$user" -x chromium || true
fi

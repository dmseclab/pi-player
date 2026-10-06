#!/usr/bin/env bash
set -euo pipefail
LOG=/var/log/pi-player/watchdog.log
mkdir -p "$(dirname "$LOG")"
log(){ printf '%s %s\n' "$(date -Is)" "$*" >> "$LOG"; }
if ! curl --noproxy '*' -fsS --max-time 5 http://127.0.0.1:8000/api/health >/dev/null; then
  log "API health failed; restarting pi-player-api.service"
  systemctl restart pi-player-api.service
  sleep 5
fi
if ! pgrep -x chromium >/dev/null 2>&1; then
  log "Chromium process missing; restarting tty1 kiosk session"
  systemctl restart getty@tty1.service
fi
# A live Chromium process can still have a frozen renderer.
if status="$(curl --noproxy '*' -fsS --max-time 5 http://127.0.0.1:8000/api/player/watchdog)"; then
  if printf '%s' "$status" | python3 -c 'import json,sys; sys.exit(0 if json.load(sys.stdin).get("stalled") else 1)'; then
    log "Kiosk heartbeat stale; restarting tty1 graphical session"
    systemctl restart getty@tty1.service
  fi
fi

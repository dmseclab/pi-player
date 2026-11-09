#!/usr/bin/env bash
set -euo pipefail
LOG=/var/log/pi-player/watchdog.log
GPU_MONITOR=/opt/pi-player-rk/deploy/pi-player-gpu-watchdog.py
mkdir -p "$(dirname "$LOG")"
log(){ printf '%s %s\n' "$(date -Is)" "$*" | tee -a "$LOG"; }

# The timer has a single watchdog owner; perform at most one restart per run.
if ! curl --noproxy '*' -fsS --max-time 5 http://127.0.0.1:8000/api/health >/dev/null; then
  log "API health failed; restarting pi-player-api.service"
  systemctl restart pi-player-api.service
  exit 0
fi
if ! pgrep -x chromium >/dev/null 2>&1; then
  log "Chromium missing; restarting tty1 kiosk session"
  systemctl restart getty@tty1.service
  exit 0
fi
# Existing heartbeat-based kiosk recovery remains in place.
if status="$(curl --noproxy '*' -fsS --max-time 5 http://127.0.0.1:8000/api/player/watchdog)"; then
  if printf '%s' "$status" | python3 -c 'import json,sys; sys.exit(0 if json.load(sys.stdin).get("stalled") else 1)'; then
    log "Kiosk heartbeat stale; restarting tty1 graphical session"
    systemctl restart getty@tty1.service
    exit 0
  fi
fi

# Optional conservative GPU monitor. No restart on a single high sample.
if [[ -f "$GPU_MONITOR" ]]; then
  set +e
  output="$(python3 "$GPU_MONITOR" 2>&1)"
  result=$?
  set -e
  if [[ $result -eq 10 ]]; then
    log "GPU resource threshold sustained; controlled tty1 kiosk recovery: $output"
    systemctl restart getty@tty1.service
  elif [[ $result -ne 0 ]]; then
    log "GPU monitor error (no recovery): $output"
  else
    # Samples visible in journal; prevent endless growth of watchdog.log.
    printf '%s\n' "$output"
  fi
fi

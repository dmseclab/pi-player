#!/usr/bin/env bash
set -euo pipefail
LOG=/var/log/pi-player/watchdog.log
GPU_MONITOR=/opt/pi-player-rk/deploy/pi-player-gpu-watchdog.py
RECOVERY_GATE=/opt/pi-player-rk/deploy/pi-player-recovery-gate.py
PENDING_KIOSK=/var/lib/pi-player/kiosk-recovery-pending
mkdir -p "$(dirname "$LOG")"
authorize(){
  if [[ ! -f "$RECOVERY_GATE" ]]; then log "Recovery gate missing; restart denied"; return 1; fi
  python3 "$RECOVERY_GATE" "$1"
}
log(){ printf '%s %s\n' "$(date -Is)" "$*" | tee -a "$LOG"; }
restart_service(){
  local kind="$1" unit="$2"
  # --no-block queues the systemd job; timeout also covers a wedged D-Bus call.
  if timeout -k 5s 25s systemctl --no-block restart "$unit"; then
    log "$kind restart queued: $unit (not yet verified)"
    if [[ "$kind" == kiosk ]]; then
      mkdir -p "$(dirname "$PENDING_KIOSK")"
      date -Is > "$PENDING_KIOSK"
    fi
  else
    log "$kind restart command failed/timed out: $unit"
  fi
}

# The timer has a single watchdog owner; perform at most one restart per run.
if ! curl --noproxy '*' -fsS --max-time 5 http://127.0.0.1:8000/api/health >/dev/null; then
  if authorize api; then
    log "API health failed; authorized restart pi-player-api.service"
    restart_service api pi-player-api.service
  else log "API health failed; automatic recovery suppressed"; fi
  exit 0
fi
if ! pgrep -u pi-player -x chromium >/dev/null 2>&1; then
  if authorize kiosk; then
    log "Chromium missing; authorized restart tty1 kiosk session"
    restart_service kiosk getty@tty1.service
  else log "Chromium missing; automatic recovery suppressed"; fi
  exit 0
fi
# Existing heartbeat-based kiosk recovery remains in place.
if status="$(curl --noproxy '*' -fsS --max-time 5 http://127.0.0.1:8000/api/player/watchdog)"; then
  if [[ -f "$PENDING_KIOSK" ]]; then
    if printf '%s' "$status" | python3 -c 'import json,sys; d=json.load(sys.stdin); sys.exit(0 if d.get("stalled") is False and isinstance(d.get("heartbeat_age_seconds"),(int,float)) else 1)'; then
      log "Previous kiosk restart verified: fresh heartbeat reported"
    else
      log "Previous kiosk restart NOT verified: heartbeat still stale or invalid"
    fi
    rm -f "$PENDING_KIOSK"
  fi
  if printf '%s' "$status" | python3 -c 'import json,sys; sys.exit(0 if json.load(sys.stdin).get("stalled") else 1)'; then
    if authorize kiosk; then
      log "Kiosk heartbeat stale; authorized restart tty1 graphical session"
      restart_service kiosk getty@tty1.service
    else log "Kiosk heartbeat stale; automatic recovery suppressed"; fi
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
    if authorize kiosk; then
      log "GPU resource threshold sustained; controlled tty1 kiosk recovery: $output"
      restart_service kiosk getty@tty1.service
    else log "GPU resource threshold sustained; recovery suppressed: $output"; fi
  elif [[ $result -ne 0 ]]; then
    log "GPU monitor error (no recovery): $output"
  else
    # Samples visible in journal; prevent endless growth of watchdog.log.
    printf '%s\n' "$output"
  fi
fi

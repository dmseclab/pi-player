#!/usr/bin/env bash
# Code update with a verified local snapshot; never rerun appliance provisioning.
set -Eeuo pipefail
[[ $(id -u) == 0 ]] || { echo 'Run with sudo -E bash deploy/update.sh' >&2; exit 1; }
APP_DIR="${PI_PLAYER_APP_DIR:-/opt/pi-player-rk}"
DATA_DIR="${PI_PLAYER_DATA_DIR:-/var/lib/pi-player}"
BACKUP_ROOT="${PI_PLAYER_BACKUP_ROOT:-/var/backups/pi-player}"
SOURCE_DIR="$(cd "$(dirname "$0")/.." && pwd)"
WATCHDOG_WAS_ACTIVE=0; HEALTH_WAS_ACTIVE=0
systemctl is-active --quiet pi-player-watchdog.timer && WATCHDOG_WAS_ACTIVE=1 || true
systemctl is-active --quiet pi-player-health.timer && HEALTH_WAS_ACTIVE=1 || true
[[ -x "$APP_DIR/.venv/bin/python" && -d "$DATA_DIR" ]] || { echo 'Installed runtime or data directory not found' >&2; exit 1; }
owner="$(stat -c '%u:%g' "$APP_DIR")"
mkdir -p "$BACKUP_ROOT"; chmod 700 "$BACKUP_ROOT"
work="$(mktemp -d "$BACKUP_ROOT/.update-XXXXXX")"
backup=""; changed=0; stopped=0
resume_timers() {
  if [[ $WATCHDOG_WAS_ACTIVE == 1 ]]; then systemctl start pi-player-watchdog.timer; fi
  if [[ $HEALTH_WAS_ACTIVE == 1 ]]; then systemctl start pi-player-health.timer; fi
}
stop_runtime() {
  systemctl stop pi-player-watchdog.timer pi-player-health.timer
  systemctl stop pi-player-watchdog.service pi-player-health.service
  systemctl stop pi-player-api.service
  stopped=1
}
restore_snapshot() {
  local snapshot="$1"
  [[ -f "$snapshot/complete" && -d "$snapshot/application/.venv" && -d "$snapshot/data" ]] || { echo 'Snapshot is incomplete' >&2; return 1; }
  rsync -ac --delete "$snapshot/application/" "$APP_DIR/"
  rsync -ac --delete "$snapshot/data/" "$DATA_DIR/"
}
health_check() {
  local expected="$1" response
  for attempt in $(seq 1 45); do
    if response="$(curl --noproxy '*' -fsS --max-time 2 http://127.0.0.1:8000/api/health)"; then
      if printf '%s' "$response" | python3 -c 'import json,sys; d=json.load(sys.stdin); sys.exit(not(d.get("ok") and d.get("version")==sys.argv[1]))' "$expected"; then return 0; fi
    fi
    sleep 1
  done
  return 1
}
finish_failure() {
  local result=$?
  trap - ERR
  set +e
  if [[ $changed == 1 ]]; then
    echo 'Update failed; restoring application and data snapshot.' >&2
    systemctl stop pi-player-api.service
    if restore_snapshot "$backup"; then
      systemctl start pi-player-api.service
      resume_timers
    else
      echo "Restore failed. Services remain stopped; snapshot: $backup" >&2
    fi
  elif [[ $stopped == 1 ]]; then
    systemctl start pi-player-api.service
    resume_timers
  fi
  rm -rf "$work"
  exit "$result"
}
trap finish_failure ERR
if [[ ${1:-} == --rollback ]]; then
  snapshot="$(realpath "${2:?Provide the snapshot directory}")"
  [[ "$snapshot" == "$BACKUP_ROOT/"* && -f "$snapshot/complete" ]] || { echo 'Use a completed snapshot under the backup directory' >&2; exit 1; }
else
  [[ -z ${1:-} ]] || { echo 'Usage: update.sh [--rollback /var/backups/pi-player/snapshot]' >&2; exit 1; }
  # Download before downtime. Inherited proxy/pip settings apply here.
  "$APP_DIR/.venv/bin/python" -m pip download --disable-pip-version-check -r "$SOURCE_DIR/requirements.txt" -d "$work/wheels"
  for folder in pi_player static deploy; do [[ -d "$SOURCE_DIR/$folder" ]] || exit 1; done
  "$APP_DIR/.venv/bin/python" -m compileall -q "$SOURCE_DIR/pi_player"
fi
stop_runtime
backup="$BACKUP_ROOT/$(date +%Y%m%d-%H%M%S)-$(basename "$work")"
mkdir -m 700 "$backup"
cp -a "$APP_DIR" "$backup/application"
cp -a "$DATA_DIR" "$backup/data"
touch "$backup/complete"
echo "Snapshot: $backup"
changed=1
if [[ ${1:-} == --rollback ]]; then
  restore_snapshot "$snapshot"
else
  for folder in pi_player static deploy; do
    rsync -ac --delete --exclude='__pycache__/' "$SOURCE_DIR/$folder/" "$APP_DIR/$folder/"
  done
  cp "$SOURCE_DIR/requirements.txt" "$APP_DIR/requirements.txt"
  "$APP_DIR/.venv/bin/python" -m pip install --disable-pip-version-check --no-index --find-links "$work/wheels" -r "$APP_DIR/requirements.txt"
  chown -R "$owner" "$APP_DIR"
fi
expected="$("$APP_DIR/.venv/bin/python" -c "import sys;sys.path.insert(0,'$APP_DIR');from pi_player import __version__;print(__version__)")"
systemctl start pi-player-api.service
health_check "$expected"
resume_timers
# The Pi appliance owns Chromium through its graphical tty1 session.
if systemctl is-active --quiet getty@tty1.service; then systemctl restart getty@tty1.service; fi
changed=0
rm -rf "$work"
trap - ERR
echo "Update complete: $expected"
echo "Rollback: sudo -E bash $SOURCE_DIR/deploy/update.sh --rollback $backup"

#!/usr/bin/env bash
set -euo pipefail
APP_DIR="/opt/pi-player-rk"; DATA_DIR="/var/lib/pi-player"; LOG_DIR="/var/log/pi-player"; APPLIANCE="${PI_PLAYER_APPLIANCE:-0}"
APP_USER="${PI_PLAYER_USER:-pi}"
if [[ "$APPLIANCE" == "1" ]]; then APP_USER="pi-player"; fi
[[ "$(id -u)" -eq 0 ]] || { echo "Run this installer with sudo."; exit 1; }
if ! id "$APP_USER" >/dev/null 2>&1; then
  if [[ "$APPLIANCE" == "1" ]]; then useradd -m -s /bin/bash -G video,input,render "$APP_USER"; else echo "User '$APP_USER' does not exist." >&2; exit 1; fi
fi
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y git ca-certificates curl python3 python3-venv python3-pip logrotate rsync chromium labwc seatd dbus-user-session xwayland openssh-server sudo network-manager
systemctl enable --now ssh seatd
mkdir -p "$APP_DIR" "$DATA_DIR/assets" "$DATA_DIR/tmp" "$LOG_DIR" /etc/pi-player
rsync -a --delete --exclude ".git" --exclude ".venv" --exclude "data" --exclude "*.tar.gz" ./ "$APP_DIR"/
python3 -m venv "$APP_DIR/.venv"; "$APP_DIR/.venv/bin/pip" install --upgrade pip; "$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt"
chown -R "$APP_USER:$APP_USER" "$APP_DIR" "$DATA_DIR" "$LOG_DIR"
for unit in pi-player-api.service pi-player-kiosk.service pi-player-health.service; do sed "s/^User=pi$/User=$APP_USER/; s/^Group=pi$/Group=$APP_USER/; s#/home/pi/#/home/$APP_USER/#g" "$APP_DIR/deploy/$unit" > "/etc/systemd/system/$unit"; done
install -m 0644 "$APP_DIR/deploy/pi-player-health.timer" /etc/systemd/system/pi-player-health.timer
sed "s/create 0640 pi pi/create 0640 $APP_USER $APP_USER/" "$APP_DIR/deploy/pi-player.logrotate" > /etc/logrotate.d/pi-player
install -o root -g root -m 0755 "$APP_DIR/deploy/pi-player-system" /usr/local/sbin/pi-player-system
printf '%s ALL=(root) NOPASSWD: /usr/local/sbin/pi-player-system *\n' "$APP_USER" > /etc/sudoers.d/pi-player-system; chmod 0440 /etc/sudoers.d/pi-player-system
if [[ ! -f /etc/pi-player/environment ]]; then printf 'PI_PLAYER_SESSION_SECRET=%s\n' "$(python3 -c 'import secrets; print(secrets.token_hex(32))')" > /etc/pi-player/environment; chmod 0600 /etc/pi-player/environment; fi
USER_HOME="$(getent passwd "$APP_USER" | cut -d: -f6)"; LABWC_DIR="$USER_HOME/.config/labwc"; mkdir -p "$LABWC_DIR"; AUTOSTART="$LABWC_DIR/autostart"; touch "$AUTOSTART"
START_LINE="sleep 8 && $APP_DIR/deploy/launch-kiosk.sh &"; grep -Fq "$APP_DIR/deploy/launch-kiosk.sh" "$AUTOSTART" || printf '\n# Pi Player RK kiosk\n%s\n' "$START_LINE" >> "$AUTOSTART"; chown -R "$APP_USER:$APP_USER" "$USER_HOME/.config"
if [[ "$APPLIANCE" == "1" ]]; then
  hostnamectl set-hostname pi-player
  mkdir -p /etc/systemd/system/getty@tty1.service.d
  printf '[Service]\nExecStart=\nExecStart=-/sbin/agetty --autologin %s --noclear %%I $TERM\n' "$APP_USER" > /etc/systemd/system/getty@tty1.service.d/autologin.conf
  printf 'if [ -z "$WAYLAND_DISPLAY" ] && [ "${XDG_VTNR:-}" = "1" ]; then\n    exec dbus-run-session labwc\nfi\n' > "$USER_HOME/.bash_profile"; chown "$APP_USER:$APP_USER" "$USER_HOME/.bash_profile"
  # Mark only a fresh appliance database for the mandatory setup wizard.
  "$APP_DIR/.venv/bin/python" - <<'PY'
from pi_player.db import init_db, db, set_setting
init_db()
with db() as c: set_setting(c, "setup_required", "1")
PY
fi
systemctl daemon-reload; systemctl enable pi-player-api.service; systemctl restart pi-player-api.service; systemctl enable --now pi-player-health.timer
printf 'Installed Pi Player RK%s.\n' "$([[ "$APPLIANCE" == "1" ]] && echo ' appliance' || true)"
echo "API: http://<pi-address>:8000/"; echo "Health: http://127.0.0.1:8000/api/health"; echo "Reboot to test the full kiosk boot."

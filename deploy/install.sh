#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/pi-player-rk"
DATA_DIR="/var/lib/pi-player"
LOG_DIR="/var/log/pi-player"
APP_USER="${PI_PLAYER_USER:-pi}"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run this installer with sudo."
  exit 1
fi

if ! id "$APP_USER" >/dev/null 2>&1; then
  echo "User '$APP_USER' does not exist. Set PI_PLAYER_USER to the Raspberry Pi desktop user." >&2
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive

apt-get update
apt-get install -y \
  git \
  ca-certificates \
  python3 \
  python3-venv \
  python3-pip \
  logrotate \
  rsync \
  chromium \
  labwc \
  seatd \
  dbus-user-session \
  xwayland

mkdir -p "$APP_DIR" "$DATA_DIR/assets" "$DATA_DIR/tmp" "$LOG_DIR"
rsync -a --delete \
  --exclude ".git" \
  --exclude ".venv" \
  --exclude "data" \
  --exclude "*.tar.gz" \
  ./ "$APP_DIR"/

python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install --upgrade pip
"$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt"

chown -R "$APP_USER:$APP_USER" "$APP_DIR" "$DATA_DIR" "$LOG_DIR"

for unit in pi-player-api.service pi-player-kiosk.service pi-player-health.service; do
  sed "s/^User=pi$/User=$APP_USER/; s/^Group=pi$/Group=$APP_USER/; s#/home/pi/#/home/$APP_USER/#g" \
    "$APP_DIR/deploy/$unit" > "/etc/systemd/system/$unit"
done
install -m 0644 "$APP_DIR/deploy/pi-player-health.timer" /etc/systemd/system/pi-player-health.timer
sed "s/create 0640 pi pi/create 0640 $APP_USER $APP_USER/" "$APP_DIR/deploy/pi-player.logrotate" > /etc/logrotate.d/pi-player

USER_HOME="$(getent passwd "$APP_USER" | cut -d: -f6)"
LABWC_DIR="$USER_HOME/.config/labwc"
mkdir -p "$LABWC_DIR"
AUTOSTART="$LABWC_DIR/autostart"
touch "$AUTOSTART"
START_LINE="sleep 8 && $APP_DIR/deploy/launch-kiosk.sh &"
if ! grep -Fq "$APP_DIR/deploy/launch-kiosk.sh" "$AUTOSTART"; then
  printf '\n# Pi Player RK kiosk\n%s\n' "$START_LINE" >> "$AUTOSTART"
fi
chown -R "$APP_USER:$APP_USER" "$USER_HOME/.config"

systemctl daemon-reload
systemctl enable pi-player-api.service
systemctl restart pi-player-api.service
systemctl enable --now pi-player-health.timer

echo "Installed Pi Player RK."
echo "API: http://<pi-address>:8000/"
echo "Health: http://127.0.0.1:8000/api/health"
echo "Kiosk: configured in $AUTOSTART (requires a graphical labwc session)."
echo "Reboot the Pi to test the first full hardware boot."

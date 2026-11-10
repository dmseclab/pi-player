#!/usr/bin/env bash
set -euo pipefail

URL="${PI_PLAYER_URL:-http://127.0.0.1:8000/player}"
HEALTH_URL="${PI_PLAYER_HEALTH_URL:-http://127.0.0.1:8000/api/health}"

if command -v chromium >/dev/null 2>&1; then
  BROWSER="$(command -v chromium)"
elif command -v chromium-browser >/dev/null 2>&1; then
  BROWSER="$(command -v chromium-browser)"
else
  echo "Chromium is not installed" >&2
  exit 1
fi

# Wait for the local Pi Player API before opening Chromium. This avoids a
# transient 127.0.0.1 connection-refused page during boot on slower systems.
for _ in $(seq 1 60); do
  if curl --noproxy '*' -fsS "$HEALTH_URL" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

if ! curl --noproxy '*' -fsS "$HEALTH_URL" >/dev/null 2>&1; then
  echo "Pi Player API did not become healthy within 60 seconds" >&2
  exit 1
fi

# The appliance account owns one display browser. Never launch a second
# Chromium against a live profile (including an orphan from an old session).
if pgrep -u "$(id -u)" -x chromium >/dev/null 2>&1; then
  echo "Chromium already running for the kiosk user; declining duplicate launch" >&2
  exit 0
fi

# Use a profile owned exclusively by Pi Player, not the browser's default
# interactive profile. Reap stale Singleton symlinks only when no browser
# remains alive under the dedicated kiosk account.
PROFILE_DIR="${PI_PLAYER_CHROMIUM_PROFILE:-$HOME/.config/pi-player-kiosk-chromium}"
mkdir -p "$PROFILE_DIR"
for entry in SingletonLock SingletonSocket SingletonCookie; do
  if [[ -L "$PROFILE_DIR/$entry" ]]; then
    rm -- "$PROFILE_DIR/$entry"
  fi
done

exec "$BROWSER" \\
  --user-data-dir="$PROFILE_DIR" \\
  --kiosk \
  --noerrdialogs \
  --disable-infobars \
  --disable-session-crashed-bubble \
  --disable-popup-blocking \
  --disable-background-networking \
  --disable-component-update \
  --disable-sync \
  --no-first-run \
  --start-maximized \
  --autoplay-policy=no-user-gesture-required \
  --ozone-platform=wayland \
  "$URL"

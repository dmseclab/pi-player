#!/usr/bin/env bash
set -euo pipefail

URL="${PI_PLAYER_URL:-http://127.0.0.1:8000/player}"

if command -v chromium >/dev/null 2>&1; then
  BROWSER="$(command -v chromium)"
elif command -v chromium-browser >/dev/null 2>&1; then
  BROWSER="$(command -v chromium-browser)"
else
  echo "Chromium is not installed" >&2
  exit 1
fi

exec "$BROWSER" \
  --kiosk \
  --noerrdialogs \
  --disable-infobars \
  --disable-session-crashed-bubble \
  --no-first-run \
  --start-maximized \
  --ozone-platform=wayland \
  "$URL"

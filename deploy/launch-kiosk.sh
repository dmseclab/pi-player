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

exec "$BROWSER" \
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
  --ozone-platform=wayland \
  "$URL"

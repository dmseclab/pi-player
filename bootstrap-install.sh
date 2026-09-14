#!/usr/bin/env bash
set -euo pipefail

REPO_URL="${PI_PLAYER_REPO_URL:-https://github.com/dmseclab/pi-player.git}"
INSTALL_DIR="${PI_PLAYER_SOURCE_DIR:-/opt/pi-player-src}"
APP_USER="${PI_PLAYER_USER:-${SUDO_USER:-$(id -un)}}"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run with sudo, preserving proxy variables if required: sudo -E bash bootstrap-install.sh" >&2
  exit 1
fi

if ! id "$APP_USER" >/dev/null 2>&1; then
  echo "Target user '$APP_USER' does not exist." >&2
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive

apt-get update
apt-get install -y git ca-certificates curl

if [[ -d "$INSTALL_DIR/.git" ]]; then
  git -C "$INSTALL_DIR" fetch --all --prune
  git -C "$INSTALL_DIR" reset --hard origin/main
else
  rm -rf "$INSTALL_DIR"
  git clone "$REPO_URL" "$INSTALL_DIR"
fi

chown -R "$APP_USER:$APP_USER" "$INSTALL_DIR"
cd "$INSTALL_DIR"

export PI_PLAYER_USER="$APP_USER"
exec ./deploy/install.sh

#!/usr/bin/env bash
# Shared additive OS prerequisites for fresh installs and normal upgrades.
# No renderer activation, account migration, package removal or autoremove.
set -euo pipefail
[[ $(id -u) == 0 ]] || { echo 'Run video dependency provisioning as root' >&2; exit 1; }
case "${1:-}" in
  ""|--lists-ready) ;;
  *) echo 'Usage: video-dependencies.sh [--lists-ready]' >&2; exit 2 ;;
esac
[[ $# -le 1 ]] || exit 2
missing=()
for package in mpv ffmpeg wlrctl; do
  status="$(dpkg-query -W -f='${Status}' "$package" 2>/dev/null || true)"
  [[ "$status" == 'install ok installed' ]] || missing+=("$package")
done
if (( ${#missing[@]} )); then
  export DEBIAN_FRONTEND=noninteractive
  [[ "${1:-}" == --lists-ready ]] || apt-get update
  apt-get install -y --no-upgrade --no-remove "${missing[@]}"
fi
for binary in mpv ffmpeg ffprobe wlrctl; do
  command -v "$binary" >/dev/null || { echo "Missing required binary: $binary" >&2; exit 1; }
done
echo 'Video dependencies available; renderer activation unchanged.'

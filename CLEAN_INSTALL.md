# Pi Player — Clean Raspberry Pi installation and acceptance

**Scope:** Fresh Raspberry Pi 4 with a newly imaged, 64-bit Raspberry Pi OS / Debian 13 (trixie) environment. Tested production reference: Raspberry Pi 4, 32 GB SD, labwc / Wayland. This checklist describes the installation contract; a new-card acceptance run is still required before declaring the installer fully validated.

## Before installation

1. Use a **new SD image**, not a cloned office-Pi card. Enable SSH for a bootstrap administrator with sudo access during initial imaging. Keep the new Pi on a trusted, restricted staging LAN.
2. Supply network connectivity for Debian packages, Python dependencies and GitHub access (or prepare an approved internal mirror/proxy). Do not disable TLS certificate verification.
3. Give each device a **unique hostname** during first-time setup. The default temporary hostname is `pi-player`; two fresh devices using it simultaneously can conflict.
4. Verify local time zone. Date/time scheduling uses the Pi's local clock. For South African deployment, configure `Africa/Johannesburg` and an approved NTP source, then verify synchronization.
5. Do **not** copy `/var/lib/pi-player`, `/etc/pi-player/environment`, support credentials, SSH keys, or uploaded operational media from another Pi. Each new appliance must have a unique secret, user credentials, and its own assets.

## Install from current main

On the fresh Pi, signed in as the bootstrap administrator:

```bash
sudo apt-get update
sudo apt-get install -y git ca-certificates curl
git clone --branch main --single-branch https://github.com/dmseclab/pi-player.git
cd pi-player
git status --short --branch
sudo -E env PI_PLAYER_APPLIANCE=1 PI_PLAYER_USER="$USER" bash bootstrap-install.sh
```

The installer provisions `pi-player` as the internal kiosk user; the initial SSH/bootstrap user remains separate. Installation copies application code to `/opt/pi-player-rk`, persistent data to `/var/lib/pi-player`, and service logs to `/var/log/pi-player`.

**Important:** Do not execute this install command on an existing production appliance without separately reviewing backup and update impact. Use `deploy/update.sh` for upgrades.

## First-time configuration

1. Check local health: `curl --noproxy '*' -fsS http://127.0.0.1:8000/api/health`.
2. In a browser on the staging LAN, open `http://<pi-ip>:8000/`. The First-Time Setup wizard should appear.
3. Temporary bootstrap web credentials are `pi` / `pi`. **Use them only on the isolated staging LAN, immediately complete setup, and never leave the appliance exposed in this state.**
4. Configure a unique web admin, a distinct SSH/support user, strong unique passwords and final hostname. Confirm old bootstrap web credentials no longer work.
5. Verify NTP/time zone and then configure branding, content, playback and (if required) static network parameters.
6. Reboot once and verify automatic kiosk launch on HDMI, as well as web administration from another workstation.

## Acceptance checklist

- [ ] Pi boot/login correct; single labwc Chromium kiosk launches automatically, without a second kiosk service
- [ ] `pi-player-api.service`, `pi-player-health.timer`, and `pi-player-watchdog.timer` active
- [ ] `/api/health` returns `ok: true`, with zero missing/orphan/size-mismatched assets
- [ ] Database is new and empty before test uploads; unique `/etc/pi-player/environment` secret exists with `0600` permissions
- [ ] Admin and SSH/support credentials unique; temporary bootstrap web login rejected after setup
- [ ] Local timezone and NTP synchronized; scheduled assets use local dates/times
- [ ] Image / PDF / video / website content upload, playback and removal checked
- [ ] **Always, Scheduled and Recurring** playlist settings save and reload; expiry disables only the relevant playlist item
- [ ] Playlist export/import preserves schedule settings (subject to acceptance tests on the audit branch)
- [ ] Controlled reboot returns to playback without manual assistance; no unexpected API, Chromium or GPU watchdog restart loop
- [ ] No site-specific credentials, IPs, operational assets or private keys copied from the original player

## Diagnostics

```bash
hostnamectl
timedatectl
systemctl is-active pi-player-api.service getty@tty1.service
systemctl is-active pi-player-health.timer pi-player-watchdog.timer
curl --noproxy '*' -fsS http://127.0.0.1:8000/api/health
sudo journalctl -u pi-player-api.service -b --no-pager -n 50
```

## Security and release gate

Pi Player web administration currently uses HTTP on port 8000 and cookie-based login. Restrict it to a trusted management/staging network; do not directly publish it to the internet. Use approved HTTPS termination if network policy requires encrypted transport.

Before a fresh install, verify that the repository audit PR has been tested and merged to `main`. A clean install has **not** been proven merely because the existing office Pi is healthy.

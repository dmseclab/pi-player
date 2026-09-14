# Pi Player RK

A lightweight, locally managed Raspberry Pi OS digital-signage player built to replace an unreliable piSignage deployment.

**Current version: 0.2.0 — first Raspberry Pi hardware test candidate**

## What it does

- Upload and persist image assets locally.
- Add website-link assets.
- Build playlists with per-item durations.
- Run a full-screen Chromium player on the Pi.
- Store metadata in SQLite (WAL mode).
- Use atomic uploads (`tmp` file -> final asset path) so interrupted uploads do not replace good files.
- Keep application data outside the application directory under `/var/lib/pi-player` on Raspberry Pi OS.
- Check the database against asset files at startup and every 15 minutes.
- Report missing, mismatched, orphaned and temporary files without silently deleting them.
- Expose a lightweight `/api/health` endpoint suitable for Zabbix.
- Rotate application logs.

## Reliability design

Persistent runtime data is deliberately separated from application code:

```text
/opt/pi-player-rk/          application code
/var/lib/pi-player/
  pi_player.sqlite3         metadata/settings/playlists
  assets/                   persistent uploaded files
  tmp/                      temporary uploads
/var/log/pi-player/         application logs
```

The installer may replace `/opt/pi-player-rk` during an update, but it does **not** delete `/var/lib/pi-player`. Asset cleanup is never automatic: orphan files and metadata/file mismatches are reported for investigation.

Uploaded images are written to a temporary file, size-checked, SHA-256 hashed, moved atomically to the persistent asset directory, and only then entered into SQLite.

## Raspberry Pi hardware install

Recommended first target: Raspberry Pi OS with Desktop using the default labwc/Wayland session and desktop autologin.

```bash
git clone https://github.com/dmseclab/pi-player.git
cd pi-player
sudo PI_PLAYER_USER=pi ./deploy/install.sh
sudo reboot
```

If your Pi username is not `pi`, replace it in `PI_PLAYER_USER`.

The installer:

1. Installs Python, venv, rsync, logrotate and Chromium.
2. Copies the application to `/opt/pi-player-rk`.
3. Creates persistent data/log directories.
4. Installs and starts the API service.
5. Enables the 15-minute health timer.
6. Adds the kiosk launcher to `~/.config/labwc/autostart` for the selected desktop user.

Raspberry Pi OS currently recommends launching Chromium from labwc autostart for kiosk use; therefore the Wayland kiosk is tied to the logged-in graphical session rather than enabled as a system service. The included `pi-player-kiosk.service` remains available as an X11 fallback.

## First login

Open:

```text
http://<pi-address>:8000/
```

Default web login:

- Username: `pi`
- Password: `pi`

**Change the web password before putting a player on a production network.** Also replace the placeholder `PI_PLAYER_SESSION_SECRET` in the API service for production use.

## Health checks

Browser/API quick check:

```bash
curl http://127.0.0.1:8000/api/health
```

Manual integrity check:

```bash
cd /opt/pi-player-rk
sudo -u pi PI_PLAYER_DATA_DIR=/var/lib/pi-player PI_PLAYER_LOG_DIR=/var/log/pi-player \
  .venv/bin/python -m pi_player.health_check --checksum
```

Exit code `0` means the referenced local assets are healthy. Exit code `2` means a missing, size-mismatched or checksum-mismatched asset was found.

Useful service commands:

```bash
sudo systemctl status pi-player-api.service
sudo systemctl status pi-player-health.timer
sudo journalctl -u pi-player-api.service -f
sudo systemctl start pi-player-health.service
```

## Local development

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m uvicorn pi_player.main:app --reload --host 127.0.0.1 --port 8000
```

Development runtime data defaults to `./data`.

## First hardware test checklist

1. Install and reboot.
2. Confirm Chromium opens the local player automatically.
3. Log into the admin page from another PC.
4. Change the default web password.
5. Upload several images and create a playlist.
6. Start playback and confirm images rotate for at least one hour.
7. Reboot the Pi and confirm the playlist and uploaded assets remain.
8. Disconnect Ethernet and confirm local images continue playing.
9. Reconnect Ethernet and confirm the admin UI is reachable again.
10. Run the checksum health check and confirm `"ok": true`.

## Current limitations

Version 0.2.0 is intentionally small. Images and website links are supported; video/PDF playback, backup/export, network configuration, remote fleet management, screenshot capture and advanced display scheduling are future work.

Website assets in `embed` mode depend on the target site allowing iframe embedding. `direct` mode is intended for single-page use because navigating Chromium away from the local player prevents playlist polling until the kiosk is relaunched.

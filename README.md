# Pi Player RK

A lightweight, locally managed Raspberry Pi digital-signage player built to replace an unreliable piSignage deployment.

**Current version: 0.3.0-rc1 — hardware-tested release candidate**

## Hardware-tested baseline

The current release candidate has been tested on a Raspberry Pi 4 Model B running Debian GNU/Linux 13 (trixie), labwc/Wayland and Chromium. The tested hardware flow includes:

- automatic tty1 login and labwc kiosk startup;
- API startup before Chromium opens;
- playlist recovery after reboot;
- persistent local image assets across reboot;
- image Fit / Fill / Stretch modes;
- website Embed and controlled Direct playback;
- per-playlist-item display time;
- website zoom, test-link and page-reload options;
- portable playlist export/import including local image files;
- asset integrity checks and scheduled health monitoring.

## Features

### Assets

- Upload image assets and store them under `/var/lib/pi-player/assets`.
- Image display modes:
  - **Fit** — whole image visible, aspect ratio preserved.
  - **Fill** — fills the display, aspect ratio preserved, cropping allowed.
  - **Stretch** — fills the display exactly and may distort the image.
- Add website-link assets.
- Website display modes:
  - **Embed** — website displayed inside the local player.
  - **Direct** — website opened in a controlled Chromium window/tab while the local playlist controller remains active.
- Website zoom from 50% to 200% for Embed mode.
- Website page reload options.
- Test Link action from the admin page.

### Playlists

- Create multiple playlists.
- Add image and website assets in any order.
- Set **Display time (seconds)** independently for every playlist item.
- Enable or disable individual playlist items.
- Activate one playlist at a time.
- Export a playlist as a portable `.pi-player.zip` package.
- Import a playlist package on another player without rebuilding it manually.

Playlist packages include:

- playlist name and item order;
- per-item display time and enabled state;
- image Fit / Fill / Stretch mode;
- website Embed / Direct mode;
- website zoom and page-reload settings;
- the actual local image files used by the playlist;
- checksums for imported image validation.

Imported playlists are intentionally created **inactive** so they cannot unexpectedly replace the playlist currently playing.

## Reliability design

Persistent runtime data is separated from application code:

```text
/opt/pi-player-rk/          application code
/var/lib/pi-player/
  pi_player.sqlite3         metadata/settings/playlists
  assets/                   persistent uploaded files
  tmp/                      temporary uploads/imports/exports
/var/log/pi-player/         application logs
```

The installer may replace `/opt/pi-player-rk` during an upgrade but does **not** delete `/var/lib/pi-player`.

Uploaded images are written to a temporary file, size checked, SHA-256 hashed, moved atomically into the persistent asset directory, and only then committed to SQLite.

Asset integrity is checked at startup and every 15 minutes. Missing files, size mismatches, checksum mismatches, orphan files and temporary files are reported rather than silently deleted.

## Fresh Raspberry Pi install

The preferred deployment path is the bootstrap installer. It installs Git first, downloads or refreshes the repository, and then runs the full Pi Player installer.

If `bootstrap-install.sh` is already present on the Pi:

```bash
sudo -E PI_PLAYER_USER=richard bash bootstrap-install.sh
sudo reboot
```

Replace `richard` with the desktop/kiosk user on the target Pi.

The bootstrap installer:

1. installs Git, CA certificates and curl;
2. clones or refreshes `https://github.com/dmseclab/pi-player.git`;
3. calls `deploy/install.sh` with the selected Pi Player user.

The main installer then:

1. installs Python, venv, pip, rsync, logrotate, Chromium, labwc, seatd, dbus-user-session and xwayland;
2. copies the application to `/opt/pi-player-rk`;
3. creates persistent data and log directories;
4. installs and restarts the API service;
5. enables the 15-minute health timer;
6. configures the labwc Chromium kiosk launcher for the selected user.

## Proxy install example

If your environment requires a no-authentication HTTP proxy, export both lowercase and uppercase proxy variables before running the installer. Replace `<your_proxy_ip>` and `<proxy_port>` with values appropriate for your network:

```bash
export http_proxy=http://<your_proxy_ip>:<proxy_port>
export https_proxy=http://<your_proxy_ip>:<proxy_port>
export HTTP_PROXY=http://<your_proxy_ip>:<proxy_port>
export HTTPS_PROXY=http://<your_proxy_ip>:<proxy_port>
export no_proxy=127.0.0.1,localhost
export NO_PROXY=127.0.0.1,localhost

sudo -E PI_PLAYER_USER=richard bash bootstrap-install.sh
```

`sudo -E` is important because it preserves the proxy environment for `apt`, `git`, `pip` and other installer commands.

The kiosk and Pi Player local API use `127.0.0.1` directly and should bypass the proxy.

## Manual repository install

If Git is already installed and the repository is already cloned:

```bash
git clone https://github.com/dmseclab/pi-player.git
cd pi-player
sudo -E PI_PLAYER_USER=richard ./deploy/install.sh
sudo reboot
```

For upgrades on an existing test/player Pi:

```bash
cd ~/pi-player
git pull
sudo -E PI_PLAYER_USER=richard ./deploy/install.sh
```

The installer restarts the API service after an upgrade so updated routes and application code become active immediately.

## Kiosk startup

The player uses labwc/Wayland and Chromium. The kiosk launcher waits for the local health endpoint before opening Chromium, preventing a temporary `127.0.0.1 refused to connect` page during boot.

Typical startup flow:

```text
Pi boot
  -> tty1 autologin
  -> dbus-run-session labwc
  -> labwc autostart
  -> launch-kiosk.sh
  -> wait for /api/health
  -> Chromium kiosk
  -> /player
```

## First login

Open the admin interface from another PC:

```text
http://<pi-address>:8000/
```

Default web login:

- Username: `pi`
- Password: `pi`

Change the default web password before production use. Also replace the placeholder `PI_PLAYER_SESSION_SECRET` in the API service for production deployment.

## Health checks

Quick local health check:

```bash
curl --noproxy '*' -s http://127.0.0.1:8000/api/health
```

A healthy response resembles:

```json
{
  "ok": true,
  "version": "0.3.0-rc1",
  "missing_assets": 0,
  "size_mismatch": 0,
  "orphan_files": 0,
  "temp_files": 0
}
```

Manual checksum verification:

```bash
cd /opt/pi-player-rk
sudo -u richard \
  PI_PLAYER_DATA_DIR=/var/lib/pi-player \
  PI_PLAYER_LOG_DIR=/var/log/pi-player \
  .venv/bin/python -m pi_player.health_check --checksum
```

Replace `richard` with the installed Pi Player user.

Useful service commands:

```bash
sudo systemctl status pi-player-api.service
sudo systemctl status pi-player-health.timer
sudo journalctl -u pi-player-api.service -f
sudo systemctl start pi-player-health.service
systemctl cat pi-player-api.service | grep ExecStart
```

## Playlist backup and recovery

To move a playlist to another display:

1. Open **Playlists**.
2. Click **Export** on the playlist.
3. Save the generated `.pi-player.zip` file.
4. On the replacement Pi, click **Import Playlist Package**.
5. Select the exported package.
6. Review the imported inactive playlist.
7. Click **Activate** when satisfied.

If an imported playlist has the same name as an existing playlist, Pi Player creates a unique name such as `Playlist (2)`.

## Website behavior notes

### Embed

Embed mode keeps the website inside the Pi Player page and supports Pi Player zoom control. Some sites prohibit iframe embedding through browser security headers; those sites should use Direct mode instead.

### Direct

Direct mode opens the target website in a controlled Chromium window/tab for the configured playlist-item display time. The local Pi Player controller remains alive and closes the Direct website before moving to the next playlist item.

Website login sessions are handled by Chromium. Pi Player intentionally does not store website usernames or passwords in asset configuration.

## Hardware release-candidate validation checklist

Before deploying a newly built Pi:

1. Reboot and confirm Chromium opens the player automatically.
2. Confirm the admin page reports the correct LAN IP.
3. Upload an image and verify Fit, Fill and Stretch.
4. Verify an Embed website rotates correctly.
5. Verify a Direct website returns to the next playlist item.
6. Verify different playlist-item display times.
7. Reboot and confirm the active playlist resumes automatically.
8. Confirm all local image assets remain present after reboot.
9. Export the active playlist and import it as a test copy.
10. Confirm website zoom and reload settings survive export/import.
11. Run `/api/health` and confirm asset-integrity counters are clean.

## Current scope

The 0.3.0-rc1 release candidate supports image and website signage, playlist timing, portable playlist backup/recovery, local health monitoring and a Raspberry Pi kiosk deployment workflow.

Not currently included:

- video or PDF assets;
- fleet/cloud management;
- full-device backup/restore;
- advanced schedule/calendar playback;
- website keystroke automation;
- custom authentication headers;
- website auto-scroll.

These are intentionally excluded from the first release candidate to keep the player small, understandable and reliable.

## Local development

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m uvicorn pi_player.application:app --reload --host 127.0.0.1 --port 8000
```

Development runtime data defaults to `./data`.

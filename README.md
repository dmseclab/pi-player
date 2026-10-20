# Pi Player

Pi Player is a lightweight, locally managed Raspberry Pi digital-signage appliance designed for reliable unattended operation.

**Current stable release: v1.0.0**

Pi Player provides a browser-based management interface for adding signage content, managing playlists and operating a full-screen Chromium kiosk. Runtime data and uploaded media are stored separately from the application so software updates preserve persistent player content.

## Validated platform

Pi Player v1.0.0 has been validated on:

- Raspberry Pi 4 Model B
- 32 GB SD card
- Debian GNU/Linux 13 (trixie), aarch64
- labwc / Wayland
- Chromium

The appliance uses a dedicated internal `pi-player` account for kiosk operation. Web administration and SSH/support credentials are provisioned separately.

## Features

### Content

Pi Player supports:

- images;
- MP4 and WebM video;
- PDF documents;
- websites.

New content is added to the asset library. When an active playlist exists, newly uploaded media and website links are appended to that playlist in the disabled state so they can be reviewed and configured before playback.

### Images

Supported image display modes:

- **Fit** — display the complete image while preserving aspect ratio;
- **Fill** — fill the display while allowing cropping;
- **Stretch** — fill the display exactly, allowing distortion.

Images use a configurable playlist display duration.

### Video

Video playlist items normally use automatic timing and advance when playback reaches the natural end of the media.

The player includes unattended autoplay support, explicit media cleanup between playlist items, start-failure handling and stalled-video recovery. If a video cannot recover safely, Pi Player advances rather than permanently stopping the signage playlist.

### PDF

PDF.js is bundled locally, so PDF playback does not depend on an external CDN.

PDF assets support:

- configurable seconds per page;
- recorded page count;
- full-screen page rendering;
- restart from page 1 on each playlist visit;
- **Play all pages once** mode;
- playlist-slot-controlled playback when Play all pages once is disabled;
- portable playlist export/import.

Single-page PDFs render once per playlist visit. Missing, corrupt or password-protected PDFs are rejected or skipped safely.

### Websites

Website assets support:

- **Embed** mode;
- controlled **Direct** mode;
- configurable zoom;
- optional reload interval;
- Test Link.

Embed mode keeps the website inside the Pi Player playback surface. Sites that prohibit iframe embedding should use Direct mode.

Direct mode opens the target in a controlled Chromium window or tab for the configured playlist duration. Pi Player does not store website login credentials in asset configuration.

## Playlists

Playlists can contain mixed image, video, PDF and website content.

Playlist functionality includes:

- multiple playlists;
- one active playlist at a time;
- item enable/disable;
- item reordering;
- configurable image and website duration;
- automatic video timing;
- PDF per-page timing;
- portable playlist export/import.

Disabled items remain configured without being shown by the player. Playlist refresh failures retain the last valid playlist so a temporary API or refresh problem does not unnecessarily stop signage playback.

## Administration

The management interface is organised into:

- **Dashboard** — player status and playback information;
- **Add Content** — upload images, videos and PDFs or add website links;
- **Content** — asset library and playlist management;
- **Settings** — player configuration, branding and administrator settings;
- **Logs** — diagnostics and operational logging.

The Dashboard includes kiosk/playback telemetry such as the current asset, PDF page where applicable, recent transition information and playback errors. Remote browser previews do not count as physical-kiosk heartbeat activity.

## Branding

Pi Player v1 supports persistent appliance branding including product/company identity, support text, primary and secondary colours and optional powered-by display. Branding changes are applied to the administration interface without requiring an application restart.

## First-time appliance setup

A fresh appliance starts with DHCP and the default hostname `pi-player`.

Open:

```text
http://<pi-address>:8000/
```

An unconfigured appliance redirects administration to the First-Time Setup wizard.

Temporary bootstrap web credentials are:

```text
Username: pi
Password: pi
```

First-Time Setup provisions:

1. Pi Player web-administrator credentials;
2. a separate SSH/support account;
3. the final player hostname.

Web and SSH/support passwords require at least 9 characters. After provisioning, the temporary web credentials no longer provide normal administration access and the setup wizard is disabled. The internal `pi-player` kiosk account remains separate from the support account.

DHCP is the deployment default. Static IPv4 configuration can be performed after provisioning.

## Startup flow

```text
Pi boot
  -> tty1 autologin (internal pi-player account)
  -> dbus-run-session labwc
  -> labwc autostart
  -> launch-kiosk.sh
  -> wait for local API health
  -> Chromium kiosk
  -> startup information splash
  -> active playlist
```

If there is no playable playlist, Pi Player remains on its ready/information screen.

## Runtime layout

```text
/opt/pi-player-rk/          application code

/var/lib/pi-player/
  pi_player.sqlite3         metadata, settings and playlists
  assets/                   persistent uploaded media
  tmp/                      temporary working area

/var/log/pi-player/         application and watchdog logs
```

Application upgrades may replace `/opt/pi-player-rk` but must preserve `/var/lib/pi-player`.

## Reliability

Pi Player is designed for unattended signage operation.

### Asset integrity

Uploaded local media is staged and committed to persistent storage before being referenced by the player. Asset integrity is checked at startup and periodically by the health service.

Checks include missing assets, file-size/checksum mismatches, orphan files and temporary files. Unexpected files are reported rather than silently removed.

### Watchdog

Appliance mode installs a systemd watchdog timer. The watchdog monitors local API health, Chromium availability and kiosk heartbeat state. A missing or unhealthy component receives targeted recovery rather than automatically rebooting the appliance.

The player also contains media-level recovery logic for failed or stalled video playback.

### Playback telemetry

The physical kiosk sends local playback telemetry to the API, including current playback state, current asset/page, transitions and recent playback errors.

Telemetry is accepted only from loopback and is held in memory, so recent playback errors reset when the API restarts. A stale kiosk heartbeat can trigger controlled kiosk recovery after the configured grace period.

## Health and service checks

Useful commands:

```bash
curl --noproxy '*' -s http://127.0.0.1:8000/api/health
sudo systemctl status pi-player-api.service
sudo systemctl status pi-player-health.timer
sudo systemctl status pi-player-watchdog.timer
sudo journalctl -u pi-player-api.service -f
```

A healthy API response reports the application version, asset-integrity counts and available disk space.

## Installation

The repository includes appliance installation tooling for a clean Debian/Raspberry Pi OS system.

Example:

```bash
sudo -E \
  PI_PLAYER_BRANCH=main \
  PI_PLAYER_APPLIANCE=1 \
  PI_PLAYER_USER=<bootstrap_user> \
  ./bootstrap-install.sh
```

The installer provides the required operating-system packages and configures the Pi Player runtime, Chromium kiosk environment, health monitoring, watchdog and first-time provisioning. The production application is installed under `/opt/pi-player-rk`.

## Updating an appliance

Updates are administrator initiated. Automatic application updates are intentionally excluded.

Update the source checkout on `main`, then run:

```bash
sudo -E bash /opt/pi-player-src/deploy/update.sh
```

The updater creates a verified local snapshot, preserves persistent runtime data and appliance configuration, updates the application and dependencies, verifies API health/version and refreshes the kiosk session. If the update fails, the snapshot is restored and the updater prints the rollback command.

Backups are root-only and retained until explicitly removed. A rollback restores persistent data to the snapshot time, so changes made after the snapshot are also rolled back.

## Proxy environments

Pi Player does not contain site-specific proxy addresses. Where an outbound proxy is required, provide it through the environment:

```bash
export http_proxy=http://<proxy-address>:<proxy-port>
export https_proxy=http://<proxy-address>:<proxy-port>
export HTTP_PROXY=http://<proxy-address>:<proxy-port>
export HTTPS_PROXY=http://<proxy-address>:<proxy-port>
export no_proxy=127.0.0.1,localhost
export NO_PROXY=127.0.0.1,localhost
```

Use `sudo -E` when installation/update subprocesses need to inherit proxy variables. Local Pi Player traffic should bypass the proxy. Where HTTPS inspection is used, install the organisation CA into the operating-system trust store rather than disabling TLS verification.

## Security

Recommended production practices:

- replace temporary bootstrap credentials during First-Time Setup;
- use unique administrator and SSH/support passwords;
- use key-based SSH where practical;
- restrict management access to trusted networks;
- keep Raspberry Pi OS and Chromium patched;
- do not commit secrets, runtime databases, uploaded operational content or site-specific network information.

## Local development

Example Python development environment:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m uvicorn pi_player.application:app --reload --host 127.0.0.1 --port 8000
```

Development runtime data defaults to `./data`.

## Tests

Python tests:

```bash
python -m unittest discover -s tests
```

Player JavaScript tests:

```bash
node tests/test_player.cjs
node tests/test_pdf_player.cjs
```

For the complete admin DOM regression test, install `jsdom` outside the repository and run:

```bash
NODE_PATH=/path/to/node_modules node tests/test_admin_observers.cjs
```

Do not add `node_modules` to the repository.

## Bundled PDF.js

Pi Player bundles PDF.js under `static/vendor/pdfjs/`, including its required licenses, character maps, standard fonts and WASM helpers. This allows PDF signage playback without an external CDN.

## Release

Current stable release:

```text
v1.0.0
```

The `v1.0.0` Git tag identifies the tested release baseline. Future development should be performed on a dedicated development branch created from stable `main`, with tested changes merged back only when ready for release.

## License

See `LICENSE`.

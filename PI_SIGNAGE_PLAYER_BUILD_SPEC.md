# Pi Signage Player Replacement Build Spec

## Goal

Build a lightweight Raspberry Pi OS signage player to replace the current legacy piSignage player.

The new player must let an admin upload image assets or add website links, arrange them in a playlist, set how long each item plays, and run the sequence full-screen on the Pi. It should preserve the useful operational features of the current player while fixing reliability problems such as assets disappearing and unbounded logs.

## Current Player Observations

The legacy player showed the operational features expected from the replacement (playlist control, asset management, status, settings and logs), but local media reliability was the primary concern. Site-specific addresses, serial numbers and network details are intentionally excluded from this public repository.

## Proposed Technology

Use Python on Raspberry Pi OS:

- Backend/API: FastAPI.
- Database: SQLite with WAL mode.
- Frontend/admin UI: server-rendered templates plus small JavaScript, or a compact React/Vite UI if we want richer drag/drop editing later.
- Player engine: Chromium in kiosk mode controlled by a local player page.
- Process manager: `systemd`.
- Reverse proxy: optional nginx, but not required for a single local Pi.
- Logs: journald plus application log files managed by `logrotate`.

Python/FastAPI is a good fit because it is easy to run on Pi OS, easy to package as a systemd service, and simple to maintain over SSH. Chromium remains the right playback surface because it can display images and full website links consistently.

## Core Requirements

### Admin UI

- Login screen with configurable username/password.
- Dashboard showing:
  - Current playlist.
  - Current asset.
  - Playback state.
  - Player uptime.
  - Pi temperature.
  - Disk free/used.
  - IP address.
  - App version.
  - Recent errors.
- Asset manager:
  - Upload image files.
  - Add website links.
  - Optional future support for videos, PDFs, text notices, and RSS.
  - Rename assets.
  - Delete assets with confirmation.
  - Preview assets.
  - Sort/filter assets.
  - Download asset inventory as JSON or CSV.
- Playlist manager:
  - Create, rename, delete playlists.
  - Add uploaded images or website links to a playlist.
  - Drag items to reorder.
  - Set per-item duration in seconds.
  - Enable/disable items without deleting them.
  - Select the active playlist.
  - Start, stop, next, previous, and reload playback.
- Settings:
  - Player name.
  - Admin credentials.
  - Display orientation: landscape, portrait.
  - Resolution mode, initially read-only unless we explicitly wire Pi OS display config.
  - Network information display.
  - Optional network editing after the first stable version.
  - SSH status display.
  - Log download.
  - Factory reset.

### Playback

- Full-screen kiosk mode on Pi boot.
- The playback route should run locally, for example `http://127.0.0.1:8000/player`.
- It should play the selected playlist in order and loop continuously.
- Supported first-pass item types:
  - `image`: local uploaded `jpg`, `jpeg`, `png`, `gif`, `webp`.
  - `website`: external or internal URL rendered in an iframe or navigated frame.
- Each playlist item has its own duration.
- Player must survive network loss for local assets.
- Website links should show a visible fallback/error state if they fail to load.
- Player should poll or subscribe for playlist changes and reload without rebooting.
- Assets should never be removed unless the admin deletes them or a documented cleanup policy does so.

### Storage Reliability

To address disappearing assets:

- Store uploaded files under a dedicated directory, for example `/var/lib/pi-player/assets`.
- Store metadata in SQLite, not only in filenames or browser state.
- Use content-addressed filenames or UUID filenames to avoid collisions.
- Write uploads atomically:
  - Upload to a temporary file.
  - Validate file type and size.
  - Compute checksum.
  - Move into final storage path.
  - Commit metadata only after the final move succeeds.
- Add a periodic integrity check:
  - Verify every database asset has a file.
  - Verify orphan files are reported, not silently deleted.
  - Write findings to logs and dashboard health.
- Include export/import backup:
  - SQLite database.
  - Assets directory.
  - Settings.

### SSH

- Keep normal Pi OS SSH available on port `22`.
- Do not implement browser-based unrestricted shell execution in version 1 unless we decide it is worth the security risk.
- Admin UI should show SSH status and the Pi's current IP.
- Installation docs should include:
  - Enable SSH on Pi OS.
  - Change default `pi` password.
  - Recommended key-based access.

### Logging And Log Rotation

Implement both service logs and app logs.

- Use structured application logs in `/var/log/pi-player/`.
- Suggested files:
  - `/var/log/pi-player/app.log`
  - `/var/log/pi-player/player.log`
  - `/var/log/pi-player/error.log`
  - `/var/log/pi-player/audit.log`
- Add `/etc/logrotate.d/pi-player`:

```conf
/var/log/pi-player/*.log {
    daily
    rotate 14
    compress
    delaycompress
    missingok
    notifempty
    copytruncate
    create 0640 pi pi
}
```

- Also rely on journald limits in `/etc/systemd/journald.conf`, for example:

```conf
SystemMaxUse=100M
RuntimeMaxUse=50M
MaxRetentionSec=14day
```

### Services

Create separate systemd units:

- `pi-player-api.service`
  - Runs FastAPI/Uvicorn.
  - Serves admin UI, API, uploaded assets, and player page.
- `pi-player-kiosk.service`
  - Starts Chromium in kiosk mode after graphical session/network is ready.
  - Opens `http://127.0.0.1:8000/player`.
- Optional `pi-player-health.timer`
  - Runs periodic asset integrity and disk health checks.

## Data Model

Initial SQLite tables:

- `settings`
  - `key`
  - `value`
  - `updated_at`
- `assets`
  - `id`
  - `type`
  - `name`
  - `original_filename`
  - `storage_path`
  - `url`
  - `mime_type`
  - `size_bytes`
  - `checksum_sha256`
  - `created_at`
  - `updated_at`
  - `deleted_at`
- `playlists`
  - `id`
  - `name`
  - `is_active`
  - `created_at`
  - `updated_at`
- `playlist_items`
  - `id`
  - `playlist_id`
  - `asset_id`
  - `position`
  - `duration_seconds`
  - `enabled`
  - `created_at`
  - `updated_at`
- `playback_state`
  - `id`
  - `playlist_id`
  - `item_id`
  - `state`
  - `updated_at`
- `audit_events`
  - `id`
  - `actor`
  - `action`
  - `entity_type`
  - `entity_id`
  - `details_json`
  - `created_at`

## API Surface

First-pass API endpoints:

- `GET /api/status`
- `GET /api/settings`
- `PUT /api/settings`
- `GET /api/assets`
- `POST /api/assets/upload`
- `POST /api/assets/link`
- `GET /api/assets/{id}`
- `PUT /api/assets/{id}`
- `DELETE /api/assets/{id}`
- `GET /api/playlists`
- `POST /api/playlists`
- `GET /api/playlists/{id}`
- `PUT /api/playlists/{id}`
- `DELETE /api/playlists/{id}`
- `POST /api/playlists/{id}/items`
- `PUT /api/playlists/{id}/items/{item_id}`
- `DELETE /api/playlists/{id}/items/{item_id}`
- `POST /api/playback/start`
- `POST /api/playback/stop`
- `POST /api/playback/next`
- `POST /api/playback/previous`
- `GET /api/logs`
- `GET /api/logs/{name}/download`
- `POST /api/health/integrity-check`

## Security Notes

- Replace the current default `pi/pi` web login during setup.
- Hash passwords with Argon2 or bcrypt.
- Use CSRF protection for form actions if using server-rendered pages.
- Restrict uploaded file types and maximum upload size.
- Sanitize asset names.
- Prevent path traversal in asset downloads.
- Browser-based shell execution should be avoided or heavily restricted.
- Bind admin UI to LAN by default; optional firewall rules can restrict access further.

## Build Phases

### Phase 1: Minimum Replacement

- FastAPI app with login.
- SQLite database.
- Asset upload for images.
- Add website link assets.
- Playlist CRUD.
- Per-item duration.
- Full-screen player route.
- Systemd service for API.
- Chromium kiosk service.
- Basic status page.
- Log files and logrotate.

### Phase 2: Current Feature Parity

- Dashboard with temperature, disk, current playback, IP, uptime.
- Rename/delete assets.
- Download asset list.
- Download logs.
- Start/stop/next/previous controls.
- Display orientation setting.
- Snapshot support.
- Backup/export/import.
- Integrity checker.

### Phase 3: Improvements

- Better scheduling: active playlist by time/day.
- TV on/off schedule if CEC is available.
- Offline cache and website failure screenshots.
- Multi-zone layouts if needed.
- Remote update package.
- Health page with warnings before disk fills up.
- Optional central management for multiple Pis.

## Open Questions

- Should the first version support only images and website links, or should videos/PDFs/text notices be included immediately?
	-No for version 1 we will keep to images and web links
- Should network settings remain read-only at first, or must the admin UI be able to change static IP/Wi-Fi like the current player?
	-Network settings should be editable, static IP vs DHCP, we can implement the "local" hostspot or normal wifi after phase 3
- Do we need browser-based shell commands, or is normal SSH enough?
	-Normal ssh is enough, although a restart button to restart the player should be implemented
- Should the replacement import anything from the current piSignage install, or start clean?
	-Should be a clean install
- What maximum upload size should be allowed?
	-I think we should add this to the settings if possible, some images can be large and if we add videos it might be larger, please select a default and we can work from there
- Should playlists support schedules in version 1?
	-No schedules at this time, It should play one after the other no scheduling required

## Recommended First Implementation Choice

Start with the Phase 1 build in Python/FastAPI, SQLite, and Chromium kiosk. Keep the first release intentionally small: images, website links, playlist order, per-item durations, playback controls, SSH availability, status, and log rotation. Once that is stable on Pi OS and assets no longer disappear, add the heavier current-player features one by one.

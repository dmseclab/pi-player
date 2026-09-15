# Pi Player RK

A lightweight, locally managed Raspberry Pi digital-signage player built to replace an unreliable piSignage deployment.

**Current development line: Appliance v1 — hardware-validated foundation**

## Validated baseline

Pi Player Appliance v1 has been validated on a Raspberry Pi 4 Model B with a 32 GB SD card running Debian GNU/Linux 13 (trixie), aarch64, labwc/Wayland and Chromium.

Validated functions include:

- clean-card installation;
- dedicated internal `pi-player` kiosk account;
- SSH installed and enabled;
- mandatory first-time web provisioning;
- separate web administrator and SSH/support credentials;
- configurable hostname, default `pi-player`;
- DHCP-first networking;
- five-second startup/network splash;
- automatic kiosk startup;
- API/Chromium watchdog;
- playlist recovery after reboot;
- persistent local image assets;
- image Fit / Fill / Stretch modes;
- website Embed and controlled Direct playback;
- per-item display time;
- website zoom, test-link and reload options;
- portable playlist export/import including local images;
- asset-integrity checks and scheduled health monitoring.

## First-time appliance setup

A fresh appliance starts on DHCP with hostname `pi-player`. Open the displayed admin address:

```text
http://<pi-address>:8000/
```

While the appliance is unconfigured, normal administration is blocked and the browser is redirected to the First-Time Setup wizard.

Temporary bootstrap credentials:

- Username: `pi`
- Password: `pi`

First-Time Setup creates:

1. new Pi Player web-administrator credentials;
2. a separate SSH/support username and password;
3. the final player hostname.

Web and SSH/support passwords require at least 9 characters. After successful provisioning, the temporary web credentials no longer provide normal administration access and the setup wizard is disabled. The internal `pi-player` kiosk account remains separate from the support account.

Static IPv4 configuration is performed after provisioning from normal administration; DHCP is the deployment default.

## Assets

Images are stored persistently under `/var/lib/pi-player/assets` and support:

- **Fit** — whole image visible with aspect ratio preserved;
- **Fill** — display filled with cropping allowed;
- **Stretch** — display filled exactly, distortion allowed.

Website assets support **Embed** and controlled **Direct** modes, configurable zoom, page reload and Test Link.

## Playlists and backup

Playlists support mixed image/website assets, independent display time per item, item enable/disable and one active playlist at a time.

A playlist can be exported as a portable `.pi-player.zip` package and imported onto another player. Packages preserve item order, timing, enabled state, image mode, website mode/zoom/reload settings, local image files and checksums. Imported playlists are created inactive until explicitly activated.

This export/import workflow has been validated on the Appliance v1 hardware test player after reboot.

## Reliability design

```text
/opt/pi-player-rk/          application code
/var/lib/pi-player/
  pi_player.sqlite3         metadata/settings/playlists
  assets/                   persistent uploaded files
  tmp/                      temporary work area
/var/log/pi-player/         logs
```

Application upgrades may replace `/opt/pi-player-rk` but do not delete `/var/lib/pi-player`.

Uploaded images are staged, size checked, SHA-256 hashed and moved atomically before metadata is committed. Asset integrity is checked at startup and every 15 minutes. Missing files, size/checksum mismatches, orphan files and temporary files are reported rather than silently deleted.

Appliance mode also installs a watchdog that checks the local API and Chromium/kiosk state and performs targeted recovery.

## Appliance development install

The current development workflow starts from a clean Debian/Raspberry Pi OS installation. The planned production deployment method is a prebuilt flashable SD-card image.

```bash
sudo -E \
  PI_PLAYER_BRANCH=appliance-v1 \
  PI_PLAYER_APPLIANCE=1 \
  PI_PLAYER_USER=<bootstrap_user> \
  ./bootstrap-install.sh
```

The installer provides Git, CA certificates, curl, Python/venv, Chromium, labwc, seatd, NetworkManager, OpenSSH and Pi Player services. It creates the dedicated kiosk account, configures tty1/labwc startup, enables API/health/watchdog services, generates an appliance-specific session secret and prepares first-time provisioning on a fresh appliance database.

## Proxy environments

Pi Player contains no site-specific proxy address. Supply a proxy externally when required:

```bash
export http_proxy=http://<your_proxy_ip>:<proxy_port>
export https_proxy=http://<your_proxy_ip>:<proxy_port>
export HTTP_PROXY=http://<your_proxy_ip>:<proxy_port>
export HTTPS_PROXY=http://<your_proxy_ip>:<proxy_port>
export no_proxy=127.0.0.1,localhost
export NO_PROXY=127.0.0.1,localhost
```

Use `sudo -E` so installer subprocesses inherit the proxy. Local Pi Player traffic should bypass the proxy. Where HTTPS inspection is used, install the organisation CA in the operating-system trust store; disabling TLS verification is not part of the production appliance design.

## Startup flow

```text
Pi boot
  -> tty1 autologin (internal pi-player account)
  -> dbus-run-session labwc
  -> labwc autostart
  -> launch-kiosk.sh
  -> wait for local API health
  -> Chromium kiosk
  -> startup information splash (5 seconds)
  -> active playlist
```

With no playable playlist, the player remains on its information/ready screen.

## Health and service checks

```bash
curl --noproxy '*' -s http://127.0.0.1:8000/api/health
sudo systemctl status pi-player-api.service
sudo systemctl status pi-player-health.timer
sudo systemctl status pi-player-watchdog.timer
sudo journalctl -u pi-player-api.service -f
```

## Website behavior

**Embed** keeps the site inside Pi Player and supports player zoom. Sites that prohibit iframe embedding should use Direct mode.

**Direct** opens the target in a controlled Chromium window/tab for the configured item duration. The local controller remains alive and returns to the playlist afterwards. Website login sessions remain Chromium's responsibility; Pi Player does not store website credentials in asset configuration.

## Appliance v1 hardware validation

Confirmed on the test Raspberry Pi 4B:

- clean installation;
- appliance branch deployment;
- kiosk-account creation;
- SSH enablement;
- first-time setup enforcement and temporary-login validation;
- new web-admin credential provisioning;
- SSH/support-account provisioning;
- hostname provisioning;
- reboot after provisioning;
- normal operation after reboot;
- playlist package import;
- playlist playback after import.

## Next milestones

The appliance foundation is now validated. Planned next work:

- video assets;
- PDF assets;
- playlist package support for video/PDF;
- final System/Network administration validation;
- flashable Raspberry Pi SD-card image;
- automatic first-boot filesystem expansion and per-device initialization;
- clean-image acceptance test: **flash -> insert -> Ethernet/HDMI -> power on -> provision -> import playlist -> play**.

Automatic application updates are intentionally excluded. Updates remain administrator-initiated through the admin interface or SSH.

## Local development

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m uvicorn pi_player.application:app --reload --host 127.0.0.1 --port 8000
```

Development runtime data defaults to `./data`.

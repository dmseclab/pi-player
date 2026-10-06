# Pi Player RK

A lightweight, locally managed Raspberry Pi digital-signage player built to replace an unreliable piSignage deployment.

**Current development line: main — 0.3.0-rc7**

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
- persistent local image and video assets;
- image Fit / Fill / Stretch modes;
- MP4/WebM video upload and playback;
- unattended Chromium video autoplay;
- automatic video timing to natural media completion;
- explicit video-media cleanup between playlist items;
- stalled-video detection, one controlled recovery attempt and safe playlist continuation;
- website Embed and controlled Direct playback;
- per-item display time for images and websites;
- website zoom, test-link and reload options;
- upload progress/error feedback;
- portable playlist export/import;
- asset-integrity checks and scheduled health monitoring.

## Release candidate

### 0.3.0-rc5

RC5 is the current Appliance v1 soak-test candidate. It adds the resilient video playback lifecycle required for unattended signage operation.

Video items use **Auto** display timing and normally advance when the media reaches its natural end. Chromium is launched with unattended autoplay enabled for the dedicated kiosk session. During playback Pi Player monitors actual video progress. If progress stops for 15 seconds, one controlled `play()` recovery is attempted. If the video remains stalled, Pi Player explicitly pauses the media, detaches its source, clears video monitoring timers, removes the video element and continues safely to the next playlist item. A natural-duration plus 60-second safety ceiling provides an additional failsafe for non-looping video.

The current RC5 build is undergoing extended unattended soak testing before the video implementation is considered hardware-validated.

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

Images and uploaded videos are stored persistently under `/var/lib/pi-player/assets`.

Images support:

- **Fit** — whole image visible with aspect ratio preserved;
- **Fill** — display filled with cropping allowed;
- **Stretch** — display filled exactly, distortion allowed.

Video assets currently support MP4 and WebM uploads. Video playlist items use **Auto** timing: non-looping video advances on natural media completion rather than an arbitrary slide duration. Video playback includes explicit media cleanup and stall recovery for unattended operation.

Website assets support **Embed** and controlled **Direct** modes, configurable zoom, page reload and Test Link.

PDF assets are planned but are not yet part of the current RC5 implementation.

## Playlists and backup

Playlists support mixed image, video and website assets, item enable/disable and one active playlist at a time. Images and websites use configurable display time; video uses automatic natural-duration playback.

A playlist can be exported as a portable `.pi-player.zip` package and imported onto another player. The established package workflow preserves playlist/item configuration and local packaged assets supported by the exporter. Imported playlists are created inactive until explicitly activated.

The original image/website export/import workflow has been validated on the Appliance v1 hardware test player after reboot. Video playback itself is currently under RC5 soak testing; full portable-package validation for video remains a milestone before the appliance image is finalized.

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

Uploaded local media is staged and committed into persistent storage before being referenced by the player. Asset integrity is checked at startup and every 15 minutes. Missing files, size/checksum mismatches, orphan files and temporary files are reported rather than silently deleted.

Appliance mode installs a watchdog that checks the local API and Chromium/kiosk process state and performs targeted recovery. Video playback has an additional player-level recovery layer so a stalled media element does not permanently stop the playlist.

## Appliance development install

The current development workflow starts from a clean Debian/Raspberry Pi OS installation. The planned production deployment method is a prebuilt flashable SD-card image.

```bash
sudo -E \
  PI_PLAYER_BRANCH=main \
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
  -> Chromium kiosk (unattended autoplay enabled)
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
- playlist playback after import;
- image playback and display modes;
- video upload and playlist insertion;
- automatic video display-time UI;
- unattended video autoplay after clean boot;
- natural-end video advancement.

RC5 stall recovery and long-duration unattended video operation are currently being soak tested and are therefore not yet listed as completed hardware validation.

## Next milestones

The appliance foundation is validated and video is in RC5 soak testing. Planned next work:

- complete RC5 unattended video soak test and inspect recovery logs;
- validate portable playlist package handling for video;
- PDF assets and PDF playlist playback;
- playlist package support for PDF;
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

### PDF signage

Upload images or PDFs under **Assets → Upload Media**. PDFs use a configurable
**PDF seconds per page** timer (default 10 seconds; editable on the asset).
Pages render fullscreen, fitted to the display, without viewer controls. After
the last page, the PDF loops until its playlist item duration ends. The slot
starts once the first page renders; allow at least page count × seconds per page
if every page should be shown. Each return to the PDF starts at page 1.

Missing, corrupt and password protected PDFs are skipped. PDF files and page
timers are included in playlist export/import. Existing databases automatically
migrate their asset type constraint while retaining assets and playlist links.

PDF.js 6.4.299 is bundled under `static/vendor/pdfjs` with its Apache-2.0 license,
fonts, character maps and WASM helpers. Playback requires no external CDN.

### Consolidated main branch (0.3.0-rc6)

`main` now includes the RC5 appliance foundation, video playback and PDF signage.
Existing appliance installations retain setup state, watchdog behavior, video audio
and loop settings, playlist links and uploaded files. Updates should copy application
code while preserving the virtual environment, runtime data and system configuration.

New uploads (images, video and PDFs) and website links automatically append to the
active playlist with Enabled unchecked and a default slot of 15 seconds. Enable
them and adjust timing when ready. Without an active playlist, assets stay in the
asset library for manual assignment. Disabled additions do not restart playback.

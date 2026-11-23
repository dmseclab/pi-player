# Phase 2B — account separation design, opt-in only

The normal Pi Player currently has working Chromium/HTTP services. Do not change those service users as part of an experimental video engine. The optional broker and display agent can instead be staged as two **new dedicated Unix identities** from `deploy/pi-player-mpv.sysusers.conf` on the lab host after explicit operator approval.

- `pi-player-broker`: read-only SQLite catalog and media reads; privately owned Unix socket; no graphical display access
- `pi-player-mpv`: kiosk agent; may request only authorized FDs through the broker socket; no access to the API database write credentials
- Existing Chromium display owner and HTTP API: unchanged until a tested bridge and reliable Wayland access policy are designed

**Important compatibility blocker:** A new `pi-player-mpv` UID does not automatically own the current labwc graphical session or have permission to connect to its Wayland socket. Never weaken the compositor socket permissions broadly or make a dedicated kiosk agent root to work around this. A lab-specific trust boundary, process ownership and exclusive display authority must be verified before activation. The database's read-only broker access to live WAL/SHM must also be tested; `mode=ro` alone does not grant filesystem permissions. These accounts are **not created** by CI, staging or the normal updater.

This keeps the product simple: the existing Chromium UI stays the controller and MPV remains a physically approved optional renderer, not a second administration application.

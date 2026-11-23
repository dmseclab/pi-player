# Pi Player — optional hybrid broker staging (not activated)

The unit `deploy/pi-player-mpv-broker.lab.service` is **not** part of the ordinary installer. This is a draft of a separate unprivileged broker user and dedicated kiosk-agent user; existing API and Chromium kiosk services remain unchanged. The service is never enabled by this repository. Before first lab start, a technician must verify the runtime socket's directory/group access, the broker account's read-only ability to read catalog SQLite WAL/SHM files and media, and isolation from production assets.

**Current blocker:** `RuntimeDirectoryMode=0700` with broker-owned directory is intentionally inaccessible to the kiosk account. This is an explicit fail-closed configuration, not a working installation. The service must be revised and tested with tightly controlled shared group access before activation. No change to the existing `pi` service identity is required until the dedicated kiosk agent is proven. Do not deploy this unit as-is.

The broker daemon is one-way and supplies only verified media FDs on a Unix socket. It does not control video, launch an MPV process or switch Wayland display surfaces. Real compositor verification and secure process lifecycle remain hard gates.

# Pi Player — comprehensive lab acceptance matrix (draft)

**Feature state:** MPV hybrid playback OFF by default. **Production Construction and `main`:** frozen. Test only an approved lab installation on `pi-player`, after a verified snapshot/backup. This checklist is not a deployment authorization.

## What must not change for operators
- Web-based asset upload, rename, delete, preview and assignment to playlists
- Default playlist behavior, switching, loop and per-item playback scheduling
- Normal image and PDF rendering (no user-visible loading message)
- Website refresh behavior and mixed image/PDF/video sequence
- Brand, login, administration, status panel and network setup
- Existing Chromium-only playback works with hybrid mode disabled

## Zero-change baseline before deployment
1. Record lab hostname, OS/kernel build, Chromium/MPV/Mesa/labwc versions, EEPROM, cgroup v2 mount, active graphical session, thermal baseline and uptime.
2. Export app/database and capture the exact current Git commit, service units, permissions and last 24 hours of service logs. Verify restore from backup in an isolated environment, not on Construction.
3. Verify current API and kiosk Unix service identities. Current repository units share `User=pi`, so the hybrid broker is **not deployable yet**. A new broker identity and separate kiosk service identity require approved account migration, asset permissions and socket ACL tests.
4. Confirm watchdog heartbeat, kernel warnings, blocked tasks, NTP, network isolation, disk free space, and Chromium software decoding.
5. Verify playlist/catalog migration on a **copy** of the SQLite database before any real migration, and confirm rollback restores original state.

## Scenarios to execute with measured evidence

| Group | Tests | Required outcome |
|---|---|---|
| Baseline | Images, multi-page PDF, websites, playlist changes, new asset upload, Default behavior, scheduling boundaries | Existing Chromium functionality unchanged |
| Hybrid OFF | Playback, reboot, service restart, browser death | Same behavior as stable baseline |
| MPV video | MP4 and WebM, mute and audio, loop and natural EOF, short/long files | Controlled playback and advance to next item |
| Switching | Image → video → PDF → website → video | No overlap, black screen or abandoned surface |
| Readiness | Delayed file load, delayed first frame, no visible surface, stale MPV event | Chromium remains visible until independently witnessed frame presentation |
| Authorization | Deleted item, stopped playback, changed playlist, schedule expiry, revoked epoch, disconnect | No stale media handoff or new video |
| Media | Rename/replacement, symlink attempt, content change during verification | Only current valid catalog media can play |
| Failure | MPV crash, frozen time-pos, IPC loss, process exit before registration, stuck child/cgroup | No overlapping renderer; retain quarantine until verified empty |
| Restart | API/kiosk/broker restart independently, loss of Wayland, OS reboot | Reconcile before new render; Chromium fallback |
| Stress | Repeated uploads, asset replacement, 100+ video transitions, 24h+ soak | Stable memory, CPU, thermal and file-descriptor counts |
| Network | Ethernet/Wi-Fi switch, hotspot isolation, DHCP scope, captive local management | Existing network functions behave as approved |
| Operational | Logs, health, status, operator notifications, backup/restore | Diagnosable failures and straightforward recovery |

## Explicit GO / NO-GO
- **NO-GO:** shared API/kiosk identity; no trusted cgroup inventory; unverified root permissions; incomplete owner/connection identity checks; missing verified frame witness; inability to restore Chromium; failed SQLite backup/migration test; crash/reboot that cannot recover within the approved maintenance strategy.
- **GO only for lab opt-in:** dedicated identities and permissions verified; secure broker listening socket and FD lifecycle proven; serial launch/cancellation with stable process identity; cgroup cleanup confirmed; compositor-side first-frame witness and rollback implemented; operator signs off backup and revert plan.
- **GO for production promotion:** repeatable complete lab test + extended soak + verified recovery behavior, operator review, explicitly approved `development` → `main` promotion. Never automatically promote.

## Engineering gaps after this checkpoint
- Current source units still use the same `pi` account.
- No real service socket listener, privilege migration, production-safe broker runtime or asynchronous disconnect owner cleanup.
- No cgroup-creating launcher, verified child/descendant reconciliation or actual process recovery.
- No trusted compositor-side frame-present observer and live Chromium/MPV focus/z-order switch.
- No reversible lab installer changes; mixed-media screen tests, stress and hardware soak outstanding.

**Simplification policy:** do not add a second administration UI or playlist system. The hybrid engine should be disabled unless explicitly selected for the lab. Only expand supporting modules when needed for process isolation, media authorization or recovery.

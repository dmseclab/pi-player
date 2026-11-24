# Pi Player — hybrid video engineering checkpoint

**Branch:** `development` only. **Operating mode:** original Chromium signage; MPV remains disabled. **Protected:** `main`, Construction, existing lab services. No live installation has occurred.

## Keep the design simple

One existing admin interface, playlist/scheduler, asset store and Chromium renderer. MPV is only an optional specialist for video; images, PDF, websites and the current UI stay unchanged. Do not create a second playlist engine, public MPV HTTP control API, or separate administration screens. Avoid invasive service migrations before a physical proof that MPV materially improves decoder reliability.

## Offline implementation available

- Existing catalog/owner state machine, immutable metadata and checksum validation, SQLite replay generation and WAL tests
- Linux AF_UNIX peer-authenticated descriptor transport and a local opt-in broker service
- One-request broker protocol, FD-backed MPV adapter and systemd user-scope launcher foundations
- Owner quarantine and cgroup-empty retirement evidence
- labwc/wlrctl focus adapter with Chromium rollback attempt and uniquely identified fullscreen MPV surface
- Disconnected account separation proposal (broker and MPV agent) and a reversible **disabled service-unit staging** script
- Read-only platform preflight and manually approved bounded video trial CLI
- GitHub CI regression suite

## Why this is NOT ready for full hybrid deployment

1. **Current visual scheduling not wired:** the actual Chromium player still handles video elements. There is no secure, trusted bridge from the existing `static/player.js` media selection to the optional kiosk MPV agent. Do not activate a second concurrent scheduler.
2. **Display witness missing:** `wlrctl` focus/list does not prove a Wayland frame was presented, and a trusted surface-to-MPV PID association must be established. Blind focus switching risks a black screen.
3. **Account permissions unknown:** repository service templates use `User=pi`; the actual lab system may differ. Broker read-only SQLite WAL access and new agent access to the existing compositor are unverified. Do not weaken the Wayland runtime directory or share database write permissions.
4. **Process lifecycle not hardware-verified:** `systemd-run --user --scope` FD inheritance, cgroup identity, live D-state behavior, and recovery after killed or stuck descendants must be observed on lab hardware. No absence of a process control file may be treated as proof of cleanup.
5. **Installation staging only:** the reversible staging tool handles only a new disabled broker unit. It is not an end-to-end migration of accounts, graphical sessions, API or playlist. A complete rollback plan must include this missing integration.

## Laboratory read-only information required before next implementation decision

On the lab Pi, *without changing files or restarting services*, collect:

```bash
hostname
for unit in pi-player-api.service pi-player-kiosk.service; do
  systemctl show "$unit" -p User -p Group -p MainPID -p ActiveState -p FragmentPath --no-pager
done
id pi 2>/dev/null || true
id pi-player 2>/dev/null || true
ps -eo user:20,pid,comm,args | grep -E '[l]abwc|[c]hromium|[u]vicorn|[m]pv' | cut -c1-180
command -v mpv || true
command -v wlrctl || true
command -v systemd-run || true
findmnt -n -o FSTYPE /sys/fs/cgroup
ls -ld /var/lib/pi-player /var/lib/pi-player/assets 2>/dev/null || true
```

Avoid pasting unrelated process environment variables, tokens, passwords or private files. The user has not approved any Pi changes; this is a proposed future read-only check, not a script executed by the assistant.

## Next engineering decision

First establish the real lab account/Wayland constraints from the read-only results. Then choose the simplest identity layout, prove the isolated MPV trial with physical recovery access, and only then wire the existing browser playlist to a single kiosk-owned renderer. Build a reversible lab installer for that exact layout and confirm source-unit/API/asset-data restore from a verified snapshot. **Only then** declare full mixed-media lab deployment testing ready.

Avoid delivering a misleading green light merely because Python unit tests or standalone prototypes pass.

## 24 November lab inspection and installation contract

Read-only inspection confirmed the appliance account `pi-player` owns API, Chromium and labwc; seat0 is active, the user manager runs, and cgroup v2 is mounted. The live Wayland socket is `wayland-0` inside the account's private runtime directory. API health and both timers are healthy. MPV and FFmpeg exist; `wlrctl` is absent but an arm64 Debian trixie candidate is available. The local checkout is clean at `6527c36ad48702955f62ac923fed8916dfe52a67` on the legacy experimental branch; preserve it before syncing. No device changes performed.

For the first isolated hardware trial, prefer the existing graphical account rather than migrating compositor ownership. This is not a decision to collapse broker security boundaries in the released integration. New-device provisioning must install and configure all required dependencies automatically; the installer now includes MPV, FFmpeg and wlrctl without enabling hybrid playback. Upgrade dependency handling, dynamic session discovery, secure integration, reversible deployment and clean-image acceptance are still release gates. No manual package installation may be a prerequisite for a released player.

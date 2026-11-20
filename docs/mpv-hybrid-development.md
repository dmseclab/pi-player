# MPV hybrid playback — development checkpoint

This is **Phase 1**, a deliberately isolated MPV adapter. It is not registered with FastAPI, is not enabled by default, and does not change Chromium, playlist selection, scheduling, watchdog timers, or any installed service.

## Architecture

- Existing browser `static/player.js` remains the playlist and scheduling authority.
- `pi_player/mpv_player.py` is a kiosk-account-only process adapter. It starts a single MPV A2 software-decoding child, exposes process/position status over a private Unix IPC socket, and refuses stale-session stop requests.
- The API service and graphical kiosk run as different Unix accounts in current deployments. **Do not** call `MpvPlayer.start` directly from an API worker or run it as root. A separately authenticated kiosk-side control channel is needed before integration.
- Client must resolve media IDs through the DB and check active playlist ownership; the adapter additionally constrains the resolved path to a regular video file directly under `ASSET_DIR`.
- MPV playback must remain opt-in until full mixed-media transition, startup/EOF, loop/mute, focus, display-mode, restart, and recovery tests pass.
- Existing Chromium video path remains the fallback.
- **No production deployment or service restart is part of this change.**

## Developer checks

```bash
python3 -m unittest discover -s tests -p 'test_mpv_player.py' -v
node tests/test_player.cjs
```

The unit tests mock process launch. They cannot establish Wayland display correctness, media performance, or integration behavior. These require lab hardware acceptance.

## Next phase

Define and test a kiosk-owned Unix socket control agent and its API relay, with a secure local caller identity, session/request sequencing, 30-second startup timeout, actual progress/EOF, and fail-safe renderer handover. Avoid changing the current watchdog recovery policy before validating the integrated renderer.

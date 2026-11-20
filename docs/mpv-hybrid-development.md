# MPV hybrid playback — Phase 1 hardening checkpoint

The isolated kiosk-owned MPV adapter is **NOT integrated, enabled, or accepted for deployment**. Chromium continues to own every asset. No live Pi system has been updated.

## Phase 1 review findings

Codex review of `dee9a1c6` found startup/EOF ambiguity, IPC message parsing problems, stalled-child retirement risk, and missing Unix account isolation. This checkpoint improves bounded JSON IPC reply parsing, distinguishes `starting` from observed `playing`, records unverified exits without claiming EOF, and adds tests for failed launches, missing sockets and mixed IPC frames. IPC/progress are still insufficient to confirm rendered frames. The class is not a supervisor and does not recover wedged children.

The installer currently permits the API and kiosk to run under the same Unix account. It is therefore **incorrect to consider the existing UID check a security boundary**. Do not expose MPV controls through HTTP. Phase 2 requires an explicit service-account migration and kiosk-side agent with peer credentials, authorized asset IDs, complete process lifecycle ownership, and controlled graphical handover. Preserve the existing API and kiosk service during that work.

## Testing

```bash
python3 -m unittest discover -s tests -p 'test_mpv_player.py' -v
python3 -m unittest discover -s tests -v
node tests/test_player.cjs
node tests/test_pdf_player.cjs
```

Tests must run with disposable `PI_PLAYER_DATA_DIR` and `PI_PLAYER_LOG_DIR`. Lab hardware acceptance is needed for actual video readiness, end-of-file events, fade/focus, all display modes, audio, looping, watchdogs and recovery. **Do not interpret exit code zero as media EOF.**

## Phase 1C progress-state correction

The Phase 1B independent review found that a fixed positive MPV time position was incorrectly reported as `playing`. The controller now requires **two ordered position samples with a measured increase** before returning `playing`, and returns `stalled` if no further progress is observed for 15 seconds. It rejects negative/nonfinite or overflowing positions, older out-of-order polls, invalid stop timeouts, and boolean IPC reply IDs. Reads use an end-to-end monotonic IPC deadline, including send. Unexpected process exit releases the private IPC directory.

These checks do not prove rendered frames. Playback EOF, restart supervision, installer UID separation, secure control IPC, TOCTOU-resistant file opening, and handoff remain future work. No runtime API or kiosk integration is enabled. Run Codex revalidation before acceptance.

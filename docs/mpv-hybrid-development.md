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

## Phase 1D — invalid-sample and cumulative-motion correction

The Phase 1C independent report found negative/nonfinite values could leak into position tracking, revive a stalled session, or change the comparison baseline. Phase 1D now assigns a position to the playback state machine **only after complete validation**. Invalid samples keep the previous baseline and progress clock intact. Sub-threshold advances accumulate against a stable baseline; rewinds establish a new baseline without being interpreted as progress. Very large stop timeout integers are rejected by range checks before finite conversion. The post-exit stop contract is explicitly false after status has retired the session.

New tests cover invalid samples during stalls, negative samples between identical valid positions, cumulative advances below the per-poll threshold, and the retired-session contract. These commits require independent Linux CI confirmation before Phase 1D acceptance. Secure kiosk supervision, true rendered-frame readiness, EOF events, media open race mitigation and UID separation remain unimplemented.

## Phase 1E — subthreshold rewind regression

Phase 1D was accepted **PASS WITH FINDINGS** by independent Ubuntu validation (177 Python passes, 15 MPV passes, no Critical/High defects). Its Medium finding was that a backward movement above the saved 50 ms accumulation baseline could be missed. Phase 1E records the latest *valid* sample separately, detects any backward movement against that sample, and resets the accumulation baseline. Invalid IPC positions do not alter either baseline. Added deterministic tests for `1.00 -> 1.04 -> 1.02 -> 1.06 -> 1.08` and an invalid value inserted before a rewind. **This change is not test-accepted until its new exact-commit CI and Codex results are reviewed.**

Next stage: design an unprivileged kiosk-owned process supervisor and an authenticated control transport. Do not enable MPV or alter production/kiosk accounts before completing and accepting the design. Do not promote to `main` until lab hardware soak and full acceptance.

## Phase 2A — offline supervisor policy baseline

The latest Phase 1E report accepted the isolated controller for Phase 2 supervisor development (179 Python passes, 17 MPV passes; no Critical/High/Medium defects). An exact-boundary progress comparison correction (50 ms, using a 1 ns float tolerance) and dedicated regression tests were then committed. **Phase 2A changes are not accepted until exact-commit CI/Codex validation.**

`pi_player/mpv_supervisor.py` is an **offline, side-effect-free contract**, NOT an installed supervisor. Nothing imports it in the running application. No API route, control listener, browser bridge, service unit or startup hook exists. It cannot start/kill processes, authenticate Unix peers or open media. The `AuthorizedVideo` value is only a future broker response schema: constructing it is not proof of permission. A real broker must mint grants only after authenticated UID checks, playlist/schedule authorization, and secure media opening.

Protocol version 1 accepts three exact JSON request shapes, each limited to 4096 bytes and rejecting extra fields, paths, URLs, environment overrides and arbitrary MPV arguments:

- `start`: UUID `request_id`, UUID `item_id`, `playlist_revision`, integer `generation`.
- `stop`: UUID `request_id`, UUID `session_id`, `playlist_revision`, integer `generation`.
- `status`: UUID `request_id`, UUID `session_id`.

An offline `begin` additionally requires a matching, unexpired broker grant. Only one session may be active. Duplicate active starts are idempotent; replayed completed starts and unrelated concurrent starts are rejected. Stale session/playlist generations cannot stop a replacement. The 30-second startup deadline requires **both** trusted observed playback progress and a trusted compositor surface-readiness signal for the expected MPV entry. Neither event may be manufactured from the public browser or ordinary heartbeat. A matching `end-file` with `reason=eof` completes only an accepted non-looping session; errors and early exits do not. Loops remain under Chromium duration control. No action in this policy module currently performs physical display handover.

### Phase 2B next engineering boundary

1. Implement a kiosk-owned **single process** supervisor as a graphical session service, with systemd cgroup supervision and explicit orphan/D-state quarantine. This is not the same as the offline state machine.
2. Design and independently test a secure local bridge and media broker using verified Unix peer credentials, without adding publicly reachable MPV control routes. The current installer uses the same account for API and kiosk; do not claim otherwise.
3. Plan a reversible lab-only migration to separate API and kiosk identities, preserving existing data, autologin, watchdog, and fallback. Review the installer and updater together before any permission changes.
4. Implement real `file-loaded`/`end-file` event correlation, trusted progress and Wayland readiness evidence, and rollback-safe Chromium handover. Remain **feature-off by default** until lab validation.
5. Recheck precise MPV A2 switches and test mixed playlists, autoplay, scheduled changes, looping, mute, recovery, and soak on lab hardware. Construction and `main` remain frozen.

Test commands with disposable `PI_PLAYER_DATA_DIR` and `PI_PLAYER_LOG_DIR`:

```bash
python3 -m unittest discover -s tests -p 'test_mpv_player.py' -v
python3 -m unittest discover -s tests -p 'test_mpv_supervisor.py' -v
python3 -m unittest discover -s tests -v
node tests/test_player.cjs
node tests/test_pdf_player.cjs
```

## Phase 2A-2 — offline supervisor contract hardening

Independent validation at commit `0582ccd2` reported **FAIL for Phase 2B implementation**, despite green Ubuntu CI (196 passed, 2 skipped) and accepted MPV 50 ms precision. The contract still permitted deadline-edge readiness, replay after its 64-entry cache evicted an old request, and concurrent starts.

This patch locks public transitions with an `RLock` as a defense-in-depth **offline** policy measure; the deployed service must still have a single serialized owner for broker decisions, process ownership, and event delivery. A monotonic highest-generation watermark rejects older and same-generation starts even after request-cache eviction **within one owner lifetime**. Retries require the same request and loop setting **and a currently valid matching broker grant**. Startup readiness now checks the authoritative deadline when evidence arrives and requires the expected entry ID, not just a timer callback. Direct stop requests and MPV end-file reasons are strictly validated. New regression tests exercise concurrency, timed-out readiness, cache eviction, generations, duplicate grants/options, and malformed events.

**Explicit limitations:** the in-memory watermark does not survive a service restart and is **not** a substitute for the authenticated browser-owner epoch/lease. An untrusted or externally supplied `AuthorizedVideo` is not proof of media eligibility; there is no secure broker or browser authentication yet. The `_finish` policy transition vacates an offline session but does not wait for an actual child to exit; the future supervisor must retain and quarantine the renderer slot until process exit/cgroup state is confirmed. Actual `file-loaded`, progress, and compositor readiness must be authenticated, session-bound observations. No standalone socket, API endpoint, service unit, installer or production change is part of this patch.

Do not enable hybrid playback or change Pi accounts before dedicated Unix-peer authentication, secure file opening, Wayland testing, crash recovery and rollback design. Tests and CI for this exact commit remain to be independently validated.

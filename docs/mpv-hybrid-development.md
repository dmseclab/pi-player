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

## Phase 2A-3 — offline monotonic timing correction (23 November 2026)

At commit `21d33821717742763b4d25fee02591692b78c66d`, Codex reported FAIL for backward readiness evidence and the exact fractional 30-second boundary. The corrective policy stores one absolute session `startup_deadline` and uses the same inclusive `tick >= startup_deadline` check for duplicate start, readiness, and startup expiry. Ordered owner-monotonic ticks reject backward evidence before any readiness or timing transition can mutate state. Nonfinite startup intervals are rejected. New deterministic tests exercise all three fractional boundary transitions, pre-session and out-of-order evidence, backwards duplicate/expiry, timer ordering, and forced thread ordering.

**Acceptance still pending:** exact-commit Ubuntu CI and independent Codex validation. This remains offline policy only, not deployed service. The Phase 2B real kiosk owner must stamp events on its own monotonic clock rather than accepting external event timestamps; authenticate peer UIDs, establish fresh owner epochs across restarts, authorise securely opened media, correlate MPV and trusted Wayland events, and retain child ownership through confirmed termination. No production, installer, account, HTTP, Chromium, watchdog, or lab deployment changes are introduced.

## Phase 2A acceptance — 23 November 2026

Independent Codex verification accepted the Phase 2A-3 offline timing contract at `547d3def990ffee1f57b8f9ee4a3cb7a1f49bdea`. Exact-SHA Ubuntu CI passed 209 Python tests (two skipped) and JavaScript regression checks. Independent checks reproduced all three former fractional startup deadline defects on the prior commit, confirmed their correction, and validated monotonic evidence ordering, terminal-event races and replay protection. No Critical, High, or Medium timing findings remained.

The remaining **Low** constructor finding was that a massive `startup_seconds` integer triggered `OverflowError` during `math.isfinite` before its range check. A follow-up hardening change now checks the bounded numeric range first and adds a direct oversized-integer regression. This follow-up has separate CI acceptance requirements; it does not reopen the accepted Phase 2A-3 timing finding. No deployed functionality changes.

## Phase 2B-0 — secure owner design gate (implementation not enabled)

**Service identity and lifecycle:** A single unprivileged kiosk-session process owns the MPV child, serialized command/event mailbox and renderer slot. Maintain the renderer reservation through requested stop, startup timeout, IPC loss, cleanup and actual child/cgroup exit; an unkillable D-state child results in quarantine and NO automatic second renderer. Use a private per-session runtime directory under a controlled Unix runtime path, not user-controlled /tmp. The service must never accept generic shell commands, arbitrary MPV flags, URLs or unverified media paths.

**Authority boundaries:** API and kiosk require separately audited service identities before activation; the current shared UID is not a security boundary. The future local broker authenticates peers through kernel-provided Unix credentials (not claimed UID fields), enforces explicit per-operation roles and validates playlist, schedule and asset eligibility. The broker opens media using descriptor-relative, no-follow and beneath-root constraints with stable object identity; an AuthorizedVideo dataclass is not a capability, and caller-supplied paths are forbidden.

**Owner epochs:** At every supervisor restart or owner-lease replacement, establish a fresh cryptographically unpredictable epoch, bound to the authenticated browser owner and broker; reject all old-epoch commands/grants/observations. Do not trust a browser's generation number to fence restarts. Single active owner; takeover first retires the old lease. Reconcile existing MPV processes/cgroups BEFORE admitting a new playback request.

**Trustworthy readiness:** MPV file-loaded and end-file messages must be correlated to the actual child process, IPC connection, session and entry ID. Supervisor-local `time.monotonic()` timestamps all observations; never reuse client-supplied event times for timing decisions. Positive MPV position progress proves decoding position advance, NOT visible pixels. Wayland surface readiness must be observed by a trusted kiosk/compositor-side source, independent of browser heartbeat, and tied to the expected MPV surface. Chromium retains display ownership until MPV readiness is verified; rollback restores Chromium without overlapping renderers.

**Fail-safe operation:** The Phase 2B implementation begins as OFFLINE, feature-disabled code/tests only. Do not add an enabled service, public API/HTTP endpoint, installer account change, updater integration or production wiring before separate security and lab gates. Review systemd restart behavior, log retention, watchdog interference, kiosk autologin and rollback before lab activation. Construction and `main` remain frozen.

**Proposed engineering order:** B1 local owner/epoch state model and contract tests; B2 peer-authenticated broker with fd-based media authorization; B3 single kiosk process, MPV IPC event reader and cgroup lifecycle handling; B4 trusted Wayland readiness and safe renderer handover; B5 reversible lab-only service-account migration and soak acceptance. Codex independently tests each offline checkpoint.

## Phase 2B-1 — offline owner and renderer-slot policy (not accepted yet)

`pi_player/mpv_owner.py` is an isolated policy model only, with tests in `tests/test_mpv_owner.py`. There is no integration, process spawning, Unix socket, HTTP route, installer/unit, service account, or watchdog change. **No Pi was contacted.** The model starts unreconciled, requires the future trusted cgroup inspector to assert an empty inventory, creates a random 256-bit epoch for each browser-owner lease, and fences previous epochs across replacement. Only one renderer reservation can exist. A replaced/revoked owner causes any live or reserved slot to be quarantined, and cannot free it simply by changing the lease. A bound child may be released only after the future trusted reaper proves child identity and empty process group; an unspawned reservation requires affirmative trusted proof that no launch can still occur. On supervisor restart the model starts unreconciled, so no process is admitted until an actual inventory inspection is implemented in Phase 2B-3.

**This is not a security boundary.** The caller's `owner_id`, `launch_ruled_out`, `child_id`, `group_empty`, and `reconcile_empty` are currently offline test inputs, not verified kernel facts. In particular the current implementation has no authenticated caller, browser epoch protocol, process identity binding or cgroup inspector. B2/B3 must prevent untrusted clients from invoking assertions. The broker must never expose these internal methods to the browser/API. B1 acceptance requires exact-SHA Ubuntu CI and independent Codex concurrency, stale-epoch and slot-retirement review before moving on to B2.

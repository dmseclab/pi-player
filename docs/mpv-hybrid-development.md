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

## Phase 2B-1 corrective checkpoint — late launcher acknowledgement

Codex's independent review at `db4037a1f71b3eeb53d71c84d60c2a22bdc1ecf0` found a Medium recovery defect: a spawn issued before takeover/quarantine but acknowledged afterwards could leave a quarantined slot without a recorded child. The offline policy now has `acknowledge_late_spawn(slot_id, child_id)`, a **trusted launcher-internal reconciliation transition**, accepting only a matching, still-quarantined, childless slot. It binds the child but does not revive playback, change ownership, or clear quarantine. The original stale owner's `mark_spawned` stays rejected. Cleanup still requires a matching child identity and verified empty process group. The future trusted launcher must correlate the original slot with the actual launch attempt and prevent conflicting/duplicate spawn reports, and must never expose this method to untrusted clients. In-flight launch cancellation still requires positive proof of no launch, never just a timeout. Added regressions for takeover-after-launch and quarantine-after-launch, late-ack duplicate/identity protection and epoch validation/redaction. **Acceptance requires independent adversarial review and exact-commit Linux CI.** No deployed integration, Pi contact, service, network, installer or watchdog changes.

## Phase 2B-2 first isolated security primitives — implementation review pending

`pi_player/mpv_broker.py` and `tests/test_mpv_broker.py` add a **Linux-only, non-listening** helper: authenticated kernel `SO_PEERCRED` on an already-connected `AF_UNIX` socket, distinct configured kiosk/API UIDs (fail closed if equal), trusted broker-selected asset filename validation and descriptor-relative `O_NOFOLLOW` open under an already-open asset-root fd. Nonregular objects and empty files are rejected. The caller retains an opened media descriptor pinning the underlying inode across rename/replace. The broker accepts no arbitrary request path or MPV arguments and has no socket listener. Tests cover Linux peer credentials, denied UIDs, same-UID configuration rejection, traversal, symlinks, FIFO, stale file path replacement, bad trusted records and descriptor close.

**Important limitations, no security-complete claim:** the current installed API and kiosk units both run as `pi`. Consequently this broker cannot safely activate without a separate-account migration. `OwnerLease` and `MediaRecord` are trusted direct Python inputs in this slice; this broker does NOT establish lease freshness, playlist/schedule authorization, catalog integrity, content hashes, media MIME verification, or authenticated client IPC protocol. The real broker must obtain the record from an authenticated and policy-checked catalog lookup, verify `item_id`/revision/schedule with the active owner epoch, and tie lease to kernel-authenticated connection lifetime. The asset filename schema here is a provisional single-file broker contract and must be reconciled with actual uploaded asset naming before integration. A further Linux review is required for directory ownership/permissions, mount races and descriptor handoff (e.g. `SCM_RIGHTS`) before any service is installed.

No MPV spawn, listener, API route, installer changes, Chromium wiring, user migration, watchdog changes or Pi deployment. Keep feature disabled, `main` and Construction frozen. Require exact-SHA CI plus independent security review before accepting B2.

## Phase 2B-2 descriptor lifetime correction (23 November 2026)

Independent Codex review at `da66a2561dcc20dc7313a11295c16054af999dca` found High concurrent root-descriptor close/open reuse risk and Medium root-descriptor leakage if validation after open failed. A broker-instance lock now holds the trusted root directory descriptor through the *descriptor-relative leaf open*, with close serialized under the same lock. Leaf descriptors are independently owned after successful open; close is idempotent. During construction the root fd remains a local value, is closed on every exception after opening, and is transferred to the broker only after fstat validation succeeds. Checked-in regressions force open/close interleaving, inject a root-fstat EIO and assert the descriptor was closed, and verify existing opened leaves survive broker shutdown.

**Security scope unchanged:** no broker listener, FD transfer, epoch-freshness verifier, catalog/schedule authorization, identity migration or installed service. Phase 2B-2 remains pending independent security acceptance. Low-priority exception-format consistency is deferred. Do not deploy to either Pi or promote to main.

## Phase 2B-2 catalog eligibility slice — real Pi Player SQLite schema

The isolated `pi_player/mpv_catalog.py` module resolves a **playlist item ID** against active `playlists`, `playlist_items` and non-deleted video `assets`, with the actual schedule fields. It requires enabled, currently scheduled video, an asset canonical UUID filename under the configured asset root, matching video MIME, positive size and SHA-256 digest. A deterministic SHA-256 revision fingerprints the relevant catalog fields. After the broker has opened an FD, `check_opened_media` uses `pread` to verify its bytes against the stored checksum and preserves its read offset. Twelve portable tests check eligible/ineligible rows, schedule windows, overnight recurrence, revision changes and content mutation. This is still offline code with no API/runtime coupling.

**Remaining B2 engineering, not accepted as final authorization:** actual catalog schema uses filename `asset UUID + extension`; the existing scheduling logic treats inclusive recurring end times and overnight intervals as implemented here, but cross-check full scheduling regressions before deployment. SHA-256 verification is a read-time integrity check, not an immutable inode guarantee under concurrent writes. The future broker must own an authoritative SQLite read transaction, enforce current owner epoch bound to authenticated peer and connection, validate revision across media opening/handoff, and safely transfer an FD to the kiosk with explicit per-party ownership. Account separation, Linux cross-user tests, read-only catalog DB permission policy, mount/ancestor ownership, and real cgroup/kiosk integration remain gates. No live files, endpoints, services, installers, or devices were modified.

## Phase 2B-2 catalog authorization corrective checkpoint — 23 November 2026

Independent Codex checks at `79ea49523f472087e09320fffe1c37089fc0a4fe` found three Medium issues: stopped playback or multiple active playlists could grant video; same-second edits to playback duration/loop could leave revision unchanged; and a same-size file modification during hashing could go unnoticed when metadata changed. The isolated lookup now enforces exactly one active playlist and one playback-state row, with state `playing` and matching playlist identity, within **one SQL SELECT statement**. The revision fingerprint includes duration, position, display mode, mute, loop and playback-state update as well as previous fields, independent of one-second timestamps. FD verification now compares device, inode, size, nanosecond modification and change timestamps before and after digest verification. Regression tests cover stopped/missing/inconsistent/ambiguous states, same-timestamp option edits, malformed BLOB fields, and simulated same-size metadata change during hashing; portable tests skip only the positional read cases on Windows.

**Still not full authority:** the future broker must use an authoritative transaction and recheck owner epoch, row state and descriptor identity at handoff; metadata comparison is not immutable-media publication. An open descriptor can still reference writable content, so B2 requires an ownership/permissions and atomic-publish policy, plus a safe `SCM_RIGHTS` handoff and exact kernel peer verification. Neither Raspberry Pi nor the live service was modified. Require exact-commit CI and independent validation before acceptance.

## Phase 2B-2 playback-generation replay fix — 23 November 2026

Independent Codex validation of `f9d397f78d593b5068be59fe1f04790218e18894` exposed a Medium same-second stop/restart replay: state and second-resolution `updated_at` can return to their prior values and produce the prior revision. This patch adds a persisted nonnegative `playback_generation` in `playback_state` using `install_playback_generation()` called by `init_db()`, with an idempotent SQLite `AFTER UPDATE OF state, playlist_id` trigger. Each existing API playback start/stop SQL update advances generation **within that same database transaction**, even when timestamps and state values repeat. The catalog requires the generation column and fingerprints it, rejecting pre-migration schema and malformed metadata. A fixed-timestamp stop→start regression proves the prior revision cannot recur, and an identical start request increments again. No production endpoints, service configs, hardware, or devices are changed.

**Gate:** This is a database schema migration that will run when a future development/lab installation initializes the database. It is not enabled on either Pi. Require exact-SHA CI, an independent SQLite rollback/concurrency/migration review, and controlled backup/upgrade planning before lab deployment. A lost or manually replaced DB could reset the generation: fresh owner epochs and authenticated peer fencing are still mandatory B2 controls. Ensure the trigger remains present on migrated systems and that all playback lifecycle writes remain transactional.

## Phase 2B-2 catalog migration enforcement — 23 November 2026

Independent verification of `5cb1a44bd8e26447c7723110cc24d6702c540025` found two Medium blockers: all catalog fixture tests failed because `ensure_column()` assumed `sqlite3.Row`, and a database with the generation column but without the trigger could replay same-second stop/restart revisions. `ensure_column()` now reads PRAGMA's positional name field and supports both tuple and Row factories. The canonical playback-generation trigger definition is retained in `db.py`, and the read-only catalog now refuses to issue authorization when that trigger is missing or differs from the audited definition. Migration idempotence verifies the installed definition and fails closed on a tampered trigger instead of silently trusting `IF NOT EXISTS`. New regressions cover missing/tampered triggers, same-second replay denial without the trigger, and both SQLite row factories.

**Boundary:** The trigger check and eligibility query are separate read operations in this offline module; a future broker must hold the authoritative snapshot/transaction and recheck epoch plus authorization at descriptor handoff. Trigger presence is a required schema guard, not proof against a privileged attacker modifying the database or trigger mid-operation. No live endpoints, deployment, services, Pi access, or production wiring.

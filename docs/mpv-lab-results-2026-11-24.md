# MPV laboratory evidence — 24 November 2026

Operator-reported results from the approved lab Raspberry Pi 4, Debian 13, kernel 6.18.60+rpt-rpi-v8. Source checkpoint a15a8638d03776eacc893c326be3269d5efffb22; installed application not deployed from this checkpoint. Construction and main remain unchanged. wlrctl 0.2.2-2 installed separately on lab; fresh installer now provisions it, MPV and FFmpeg. Existing-device dependency handling remains outstanding.

## Results

Chromium parent command line confirms --disable-accelerated-video-decode and Wayland; decoder internals not independently measured. Same 1080p H.264 approximately 30 fps asset used for performance comparisons. CPU percentages represent one core; RSS is summed and can double-count shared pages. MPV trials leave Chromium on a static image for performance tests. Different initial temperatures limit thermal comparisons.

| Metric | Chromium SW configured | MPV SW | MPV V4L2 copy |
|---|---:|---:|---:|
| Renderer mean CPU % | 95.4 | 56.0 | 64.6 |
| Renderer peak CPU % | 99.9 | 59.7 | 65.3 |
| Combined player mean CPU % | 95.4 | 57.9 | 67.0 |
| Mean temperature C | 41.7 | 43.7 | 41.5 |
| Peak temperature C | 43.3 | 44.3 | 43.3 |
| MPV mean RSS MiB | n/a | 185.2 | 133.1 |

Test 01: 60-second software playback; all seven operator visual checks pass, exit 0, no remaining MPV processes, Chromium visible again, kernel journal clean. Direct-render allocation failed and MPV fell back successfully. Test 02: 75-second software playback and 12 samples; exit 0. Test 03: 75-second playback and 12 samples; actual v4l2m2m-copy decoder confirmed, exit 0; physical visual observations not separately recorded. Test 04: five consecutive 16-second H.264 High Profile videos; operator reports no issues, all exit 0 and Chromium window returns to inventory, no residual MPV. PipeWire client.conf warnings with muted audio. Test 05: intentional SIGTERM exit 4 and SIGKILL exit -9, both MPV windows removed and Chromium window available; no remaining processes. With --audio=no no MPV warnings. No separate physical restoration timing reported for Test 05. No matching kernel warnings or throttling observed in these tests; API health and asset integrity remained good. These short tests do not establish extended reliability, actual dropped-frame counts, secure broker/FD lifecycle, cgroup retirement or recovery from uninterruptible kernel waits.

## Proposed implementation direction

Prefer software decoding for optional MPV renderer. Chromium remains default and owns the single playlist controller. Retain the existing appliance graphical session; do not create a second scheduler or relax Wayland runtime permissions. Test natural display restoration first and avoid explicit focus control unless necessary. Preserve configured audio behavior; --audio=no only for silent playback. Review experimental broker/owner/scope machinery for minimal secure integration: trusted local asset identifiers only, no arbitrary paths or shell commands, authenticated/authorized playback control, one renderer at a time, progress and bounded termination, quarantine if cleanup cannot be verified, Chromium fallback when safe. No assumption that same-UID processes constitute separate security identities. Avoid deleting experimental code until its required safety properties are covered by regression tests.

Release gates: actual browser-to-renderer integration with playlist timing and cancellation, asset replacement and concurrent request handling, failure fallback, installer and upgrade dependencies, verified reversible deployment, fresh-image acceptance and extended mixed-media soak. No production promotion or hybrid activation authorized by these standalone results.

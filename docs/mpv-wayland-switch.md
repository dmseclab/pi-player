# Feature-off Wayland focus adapter (labwc)

`mpv_wayland_switch.py` contains a bounded subprocess `wlrctl` focus and active-toplevel readback adapter with a Chromium rollback attempt. No shell is used. Each MPV instance is intended to have a unique `--wayland-app-id=pi-player-mpv-<uuidhex>`, supported by the Debian mpv manual. Only `OfflineHandover` can authorize the switch after separate matched progress and compositor surface evidence. This adapter does not collect that evidence itself.

**Critical limitation:** `wlrctl` foreign-toplevel focus/list is NOT proof of first-frame presentation or PID ownership, and the active-list output format must be verified on labwc 0.20.2. A trusted compositor-side surface/presentation observer is still unimplemented. Chromium's actual Wayland `app_id` must be measured on the lab before applying focus. If restored focus cannot be proven, the policy is reset but the device must report degraded and an operator may need physical access. No automatic display switching is enabled; this is testable software groundwork, not an approved lab enablement.

References: mpv stable manual `--wayland-app-id`; wlrctl Debian trixie manual `toplevel focus/list`.

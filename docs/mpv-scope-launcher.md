# Opt-in systemd scope launcher — not enabled

`pi_player.mpv_scope_launcher.ScopedMpvLauncher` prepares an unprivileged `systemd-run --user --scope` MPV command using only a broker-received FD (`/proc/self/fd/N`) and passes the descriptor explicitly via `pass_fds`. It tracks a single scope and refuses another launch until a trusted cgroup inspector proves the entire scope empty **and** the systemd-run helper has exited. It can request a whole-scope stop, but doing so never releases the scope itself. No service, API route or browser behavior changed.

**Lab verification required:** The installed Debian/systemd version's `systemd-run --user --scope` must preserve the FD to the MPV process and expose a stable `ControlGroup`. `systemd-run` PID is a helper, not necessarily MPV's PID. Its scope must contain all descendants. The control group may disappear upon successful stop; a separate trusted systemd state reconciliation will be needed to treat absence as an empty confirmed scope. Never clear quarantine merely because the directory cannot be found. In-place file modifications and privileged scope manipulation remain outside these offline guarantees.

This is a launcher building block, NOT a complete connected kiosk agent. Before activation, a real Wayland first-frame observer and host account/permissions migration must be validated. Keep Chromium as fallback.

# Experimental MPV lab trial — not the live player

`python -m pi_player.mpv_lab_trial` defaults to a **read-only preflight**. There is no automatic startup, no API endpoint, no browser interception, and no change to the existing signage loop.

An operator physically present at the approved `pi-player` lab host may later choose `--live-lab --item-id <catalog UUID>` after the dedicated broker user/socket, Wayland access and cgroup scope prerequisites are validated. The CLI requests a verified FD from the broker and launches MPV through an isolated user scope, with a bounded duration and a systemd stop request. It does **not** make Chromium focus changes, establish displayed first frames, confirm cleanup, or provide a live Hybrid toggle. Lab operators must not treat the return code as evidence of screen/decoder correctness. No MPV start should be attempted without a recovery path and physical power access.

This trial is explicitly **not** the comprehensive hybrid deployment candidate. It isolates the high-risk process/FD integration so that initial hardware observations can be made without disrupting production or changing normal playlist behavior.

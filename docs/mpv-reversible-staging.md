# Pi Player — reversible broker staging, NOT deployment

This deliberately separate `deploy/stage-mpv-lab.py` tool defaults to a JSON dry-run. `--stage` can run only as root on a host whose exact hostname is `pi-player`. It installs **only a new, disabled** opt-in broker unit with a private manifest in `/var/backups/pi-player/mpv-lab-stage`; it does not enable, start, reload the kiosk, create accounts, change permissions on the existing database or activate MPV. `--rollback` removes the staged file only when its SHA-256 matches the manifest and systemd reports that it is neither active nor enabled; otherwise it refuses.

This mechanism **does not install a working hybrid player**. Existing unit users are unchanged and service account provisioning, database read permissions, renderer cgroup ownership, Wayland observation and display switching remain unimplemented. It is for safe review and staged lab preparation only. Never run on Construction.

Before any future lab activation, prepare approved dedicated account/group configuration, verify access to only required catalog/media, install a trusted compositor observer, prove child lifecycle, and test rollback on an isolated system with no existing signage interrupted.

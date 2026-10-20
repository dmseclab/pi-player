# Pi Player Deployment Notes

These notes supplement the main README for deployment and maintenance of the stable Pi Player v1 appliance.

## Runtime layout

```text
/opt/pi-player-rk/          installed application
/var/lib/pi-player/         persistent database, settings and uploaded assets
/var/log/pi-player/         application and watchdog logs
/opt/pi-player-src/         source checkout used for administrator-initiated updates
```

Persistent runtime data must remain outside `/opt/pi-player-rk`. Application updates may replace the installed application while preserving `/var/lib/pi-player`.

## Useful service commands

```bash
sudo systemctl status pi-player-api.service
sudo systemctl restart pi-player-api.service
sudo systemctl status pi-player-health.timer
sudo systemctl start pi-player-health.service
sudo systemctl status pi-player-watchdog.timer
sudo journalctl -u pi-player-api.service -f
```

API health can be checked locally with:

```bash
curl --noproxy '*' -s http://127.0.0.1:8000/api/health
```

## Updates

Pi Player application updates are administrator initiated. Automatic application updates are intentionally excluded from v1.

Update the source checkout on `main`, then run:

```bash
sudo -E bash /opt/pi-player-src/deploy/update.sh
```

The updater creates a local snapshot before changing the installed application. Persistent data and appliance configuration are preserved. If validation fails, the updater restores the snapshot and reports the rollback command.

Backups are root-only and remain until explicitly removed. A rollback restores persistent data to snapshot time.

## Development and repository hygiene

Development may be performed on a Linux VM or workstation before Raspberry Pi hardware validation.

Do not commit:

- SSH passwords or private keys;
- administrator or support credentials;
- production/session secrets;
- device serial numbers;
- site IP addresses or network diagrams;
- SQLite runtime databases;
- uploaded operational signage assets unless intentionally used as public samples;
- runtime logs or screenshots containing operational information;
- local virtual environments or dependency directories.

## Security

For deployed appliances:

- complete First-Time Setup and replace the temporary bootstrap web credentials;
- use unique web-administrator and SSH/support passwords;
- keep the generated appliance session secret private;
- use key-based SSH where practical;
- restrict management access to the trusted LAN or management network;
- keep Raspberry Pi OS and Chromium patched;
- keep site-specific proxy, network and credential information outside the repository.

The internal `pi-player` kiosk account is separate from the provisioned SSH/support account and should not be used as a general support login.

## Release baseline

The tested Pi Player v1 release is identified by Git tag:

```text
v1.0.0
```

`main` may contain documentation or later development changes after the tagged release. Production release identification should therefore use the Git tag and application version rather than assuming the current tip of `main` is identical to the v1.0.0 release commit.

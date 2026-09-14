# Deployment Notes

## Development environment

Development may be performed on a Linux VM or workstation before Raspberry Pi hardware testing.

Do not commit:

- SSH passwords or private keys.
- Production/session secrets.
- Device serial numbers.
- Site IP addresses or network diagrams.
- SQLite runtime databases.
- Uploaded signage assets unless intentionally used as public samples.
- Runtime logs or screenshots containing operational information.

## Useful service commands

```bash
sudo systemctl status pi-player-api.service
sudo systemctl restart pi-player-api.service
sudo journalctl -u pi-player-api.service -f
sudo systemctl status pi-player-health.timer
sudo systemctl start pi-player-health.service
```

## Raspberry Pi runtime locations

```text
/opt/pi-player-rk/          application
/var/lib/pi-player/         persistent database and assets
/var/log/pi-player/         application logs
```

The API service may be replaced during an application update. Persistent runtime data must remain outside `/opt/pi-player-rk`.

## Security before production

- Change the default web credentials.
- Replace the placeholder `PI_PLAYER_SESSION_SECRET`.
- Use key-based SSH where practical.
- Restrict management access to the trusted LAN/management network.
- Keep Raspberry Pi OS and Chromium patched.

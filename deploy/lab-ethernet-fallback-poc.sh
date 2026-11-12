#!/usr/bin/env bash
# Manual isolated-cable proof only, not the automatic DHCP fallback controller.
set -Eeuo pipefail
[[ $(id -u) == 0 && $(hostname -s) == pi-player ]] || { echo "Lab pi-player/root only"; exit 1; }
[[ -t 0 && -t 1 ]] || { echo "Interactive local console required"; exit 1; }
[[ -z "$(ip -4 -o addr show dev eth0 scope global)" ]] || { echo "ABORT: eth0 already has an IPv4 address"; exit 1; }
[[ -z "$(ip -4 route show default dev eth0)" ]] || { echo "ABORT: eth0 has a default route"; exit 1; }
[[ $(cat /sys/class/net/eth0/carrier) == 1 ]]
[[ $(nmcli radio wifi) == disabled ]]
[[ $(sysctl -n net.ipv4.ip_forward) == 0 && $(sysctl -n net.ipv6.conf.all.forwarding) == 0 ]]
PROFILE=pi-player-wired-fallback-poc
UNIT=pi-player-wired-fallback-poc-safety
if nmcli -g NAME connection show | grep -Fxq "$PROFILE"; then echo "Existing test profile: abort"; exit 1; fi
python3 - <<'PY'
import ipaddress, json, subprocess
wanted = ipaddress.ip_network("10.42.1.0/24")
for route in json.loads(subprocess.check_output(["ip","-j","-4","route","show","table","all"])):
    dst = route.get("dst", "default")
    if dst != "default" and ipaddress.ip_network(dst, strict=False).overlaps(wanted):
        raise SystemExit("Fallback subnet overlaps existing route")
PY
echo "Use only a direct, isolated cable to a test laptop, never the OT switch."
echo "This may replace the current wired connection; use local console."
read -r -p 'Type ISOLATED to confirm: ' CONFIRM
[[ "$CONFIRM" == ISOLATED ]] || exit 1
UUID=$(cat /proc/sys/kernel/random/uuid)
TIMER=0
cleanup() {
    set +e
    nmcli connection delete uuid "$UUID"
    if [[ $TIMER == 1 ]]; then systemctl stop "$UNIT.timer"; fi
    nmcli device status
    ip -br address
    ip -4 route
}
trap cleanup EXIT
trap 'exit 1' HUP INT TERM
# In-memory connection, never a persistent fallback profile. No DHCP server.
nmcli connection add save no type ethernet ifname eth0 con-name "$PROFILE" \
    connection.uuid "$UUID" connection.autoconnect no \
    ipv4.method manual ipv4.addresses 10.42.1.1/24 \
    ipv4.never-default yes ipv4.may-fail no ipv4.dad-timeout 3000 \
    ipv6.method disabled
systemd-run --unit="$UNIT" --on-active=12min "$(command -v nmcli)" connection delete uuid "$UUID"
TIMER=1
nmcli --wait 30 connection up uuid "$UUID" ifname eth0
ip -4 -o addr show dev eth0 | grep -F '10.42.1.1/24'
[[ -z "$(ip -4 route show default dev eth0)" ]]
echo "No wired DHCP server was started."
echo "Laptop static address 10.42.1.2/24; leave gateway and DNS blank."
echo "Test URL: http://10.42.1.1:8000"
echo "Press Enter to remove the temporary profile, or automatic cleanup in 10 minutes."
read -r -t 600 || true

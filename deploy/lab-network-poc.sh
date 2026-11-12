#!/usr/bin/env bash
# Explicit, temporary lab test only. Never invoked by installation or the API.
set -Eeuo pipefail
export LC_ALL=C
STAGE=preflight
trap 'rc=$?; printf "ERROR: stage=%s line=%s exit=%s\n" "$STAGE" "$LINENO" "$rc" >&2' ERR
[[ $(id -u) == 0 && $(hostname -s) == pi-player ]] || { echo "Lab pi-player/root only"; exit 1; }
MODE=$(printf '%s' "$*")
[[ "$MODE" == "--hotspot" ]] || { echo "Usage: sudo bash deploy/lab-network-poc.sh --hotspot"; exit 2; }
[[ -t 0 && -t 1 ]] || { echo "Run in an interactive SSH terminal, not through tee"; exit 1; }
umask 077
PROFILE=pi-player-hotspot-poc
TABLE=pi_player_hotspot_poc
SAFETY=pi-player-hotspot-poc-safety
DHCP=pi-player-hotspot-poc-dhcp
HTTP=pi-player-hotspot-poc-http
[[ $(nmcli radio wifi) == disabled ]]
[[ $(cat /sys/class/net/eth0/carrier) == 1 ]]
[[ $(sysctl -n net.ipv4.ip_forward) == 0 && $(sysctl -n net.ipv6.conf.all.forwarding) == 0 ]]
iw reg get | grep -q '^country ZA:' || { echo "ZA regulatory domain not confirmed"; exit 1; }
if nmcli -t -f TYPE connection show | grep -Eq '^(wifi|802-11-wireless)$'; then
    echo "Existing wireless profile: abort"; exit 1
fi
if nft list table inet "$TABLE" >/dev/null 2>&1; then echo "Existing test firewall: abort"; exit 1; fi
for unit in "$SAFETY.timer" "$DHCP.service" "$HTTP.service"; do
    if systemctl is-active --quiet "$unit"; then echo "Existing test unit: abort"; exit 1; fi
done
python3 - <<'PY'
import ipaddress, json, subprocess
wanted = ipaddress.ip_network("10.42.0.0/24")
for route in json.loads(subprocess.check_output(["ip","-j","-4","route","show","table","all"])):
    dst = route.get("dst", "default")
    if dst != "default" and ipaddress.ip_network(dst, strict=False).overlaps(wanted):
        raise SystemExit("Hotspot subnet overlaps existing route")
PY
WORK=$(mktemp -d /run/pi-player-hotspot-poc.XXXXXX)
chmod 0711 "$WORK"
UUID=$(cat /proc/sys/kernel/random/uuid)
KEYFILE="/run/NetworkManager/system-connections/$PROFILE.nmconnection"
[[ ! -e "$KEYFILE" ]] || { rmdir "$WORK"; echo "Existing keyfile: abort"; exit 1; }
RADIO=0; FW=0; TIMER=0; LOADED=0
cleanup() {
    trap - ERR
    set +e
    if [[ $RADIO == 1 ]]; then
        nmcli radio wifi off || echo "WARNING: radio disable command failed" >&2
    fi
    systemctl stop "$HTTP.service" "$DHCP.service" 2>/dev/null
    if [[ $(nmcli radio wifi) == disabled ]]; then
        if [[ $LOADED == 1 ]]; then nmcli connection delete uuid "$UUID"; fi
        rm -f "$KEYFILE"
        if [[ $FW == 1 ]]; then nft delete table inet "$TABLE"; fi
        if [[ $TIMER == 1 ]]; then systemctl stop "$SAFETY.timer"; fi
    else
        echo "WARNING: radio not confirmed off; firewall retained"
    fi
    rm -rf "$WORK"
    nmcli device status
    nmcli radio all
    curl --noproxy '*' --max-time 5 -sS http://127.0.0.1:8000/api/health; echo
}
trap cleanup EXIT
trap 'exit 1' HUP INT TERM
STAGE=firewall
printf '\n===== INSTALL ISOLATION FIREWALL =====\n'
cat > "$WORK/firewall.nft" <<'EOF'
table inet pi_player_hotspot_poc {
    chain input {
        type filter hook input priority -10; policy accept;
        iifname "wlan0" udp sport 68 udp dport 67 counter accept
        iifname "wlan0" ip saddr 10.42.0.0/24 ip daddr 10.42.0.1 tcp dport 18000 counter accept
        iifname "wlan0" counter drop
    }
    chain output {
        type filter hook output priority -10; policy accept;
        oifname "wlan0" udp sport 67 udp dport 68 counter accept
        oifname "wlan0" ip saddr 10.42.0.1 ip daddr 10.42.0.0/24 tcp sport 18000 ct state established counter accept
        oifname "wlan0" counter drop
    }
    chain forward {
        type filter hook forward priority -10; policy accept;
        iifname "wlan0" counter drop
        oifname "wlan0" counter drop
    }
}
EOF
nft -c -f "$WORK/firewall.nft"
nft -f "$WORK/firewall.nft"
FW=1
STAGE=profile-create
printf '\n===== CREATE TEMPORARY PROFILE =====\n'
# Root-only, volatile NetworkManager keyfile. PSK never appears in argv or journal.
mkdir -p /run/NetworkManager/system-connections
PSK=$(python3 -c 'import secrets; print(secrets.token_hex(12))')
cat > "$KEYFILE" <<EOF
[connection]
id=$PROFILE
uuid=$UUID
type=wifi
interface-name=wlan0
autoconnect=false
[wifi]
mode=ap
ssid=pi-player-local
band=bg
channel=6
ap-isolation=1
[wifi-security]
key-mgmt=wpa-psk
proto=rsn;
pairwise=ccmp;
group=ccmp;
wps-method=1
psk=$PSK
[ipv4]
method=manual
address1=10.42.0.1/24
never-default=true
[ipv6]
method=disabled
EOF
chmod 600 "$KEYFILE"
LOADED=1
nmcli connection load "$KEYFILE"
# Confirm profile fields before enabling the radio. AP isolation is a ternary,
# not a boolean; nmcli can print true or 1 (true) depending on output mode.
STAGE=profile-validation
printf '\n===== VERIFY NON-SECRET PROFILE SETTINGS =====\n'
check_setting() {
    local field="$1" expected="$2" actual
    actual=$(nmcli -g "$field" con show uuid "$UUID")
    printf '%s: %s\n' "$field" "$actual"
    if [[ "$actual" != "$expected" ]]; then
        echo "ERROR: unexpected $field (expected $expected)" >&2
        return 1
    fi
}
check_setting 802-11-wireless.mode ap
isolation=$(nmcli -g 802-11-wireless.ap-isolation con show uuid "$UUID")
printf '802-11-wireless.ap-isolation: %s\n' "$isolation"
case "$isolation" in
    true|yes|1|"1 (true)"|"1 (yes)") ;;
    *) echo "ERROR: AP isolation not explicitly enabled; aborting" >&2; exit 1 ;;
esac
check_setting ipv4.method manual
check_setting ipv6.method disabled
check_setting ipv4.never-default yes
STAGE=safety-timer
printf '\n===== ARM SAFETY TIMER =====\n'
systemd-run --unit="$SAFETY" --on-active=12min "$(command -v nmcli)" radio wifi off
TIMER=1
STAGE=hotspot-activation
printf '\n===== ACTIVATE HOTSPOT =====\n'
RADIO=1
nmcli radio wifi on
STAGE=radio-readiness
printf '\n===== WAIT FOR WLAN0 READINESS =====\n'
ready=0
for ((attempt=1; attempt<=30; attempt++)); do
    state=$(nmcli -g GENERAL.STATE device show wlan0)
    printf 'Attempt %02d: wlan0 state=%s\n' "$attempt" "$state"
    # NM_DEVICE_STATE_DISCONNECTED=30: managed, ready for activation.
    if [[ "$state" =~ ^30([[:space:]]|$) ]]; then
        ready=1
        break
    fi
    sleep 1
done
if [[ "$ready" != 1 ]]; then
    echo "ERROR: wlan0 did not become available within 30 seconds" >&2
    nmcli radio all
    nmcli device status
    rfkill list
    iw reg get
    journalctl -u NetworkManager --since "2 minutes ago" -n 40 --no-pager || true
    exit 1
fi
STAGE=hotspot-activation
if ! nmcli --wait 30 con up uuid "$UUID" ifname wlan0; then
    echo "ERROR: hotspot activation failed after wlan0 became ready" >&2
    nmcli device status
    rfkill list
    iw reg get
    journalctl -u NetworkManager --since "2 minutes ago" -n 40 --no-pager || true
    exit 1
fi
[[ $(sysctl -n net.ipv4.ip_forward) == 0 && $(sysctl -n net.ipv6.conf.all.forwarding) == 0 ]]
STAGE=dhcp
printf '\n===== START HOTSPOT DHCP =====\n'
install -d -o nobody -g nogroup -m 0750 "$WORK/leases"
cat > "$WORK/dhcp.conf" <<EOF
port=0
interface=wlan0
bind-interfaces
user=nobody
group=nogroup
dhcp-range=10.42.0.2,10.42.0.3,255.255.255.0,1h
dhcp-lease-max=2
dhcp-option=option:router
dhcp-option=option:dns-server
dhcp-leasefile=$WORK/leases/dhcp.leases
pid-file=$WORK/dnsmasq.pid
log-dhcp
EOF
dnsmasq --test --conf-file="$WORK/dhcp.conf"
systemd-run --unit="$DHCP" --property=RuntimeMaxSec=660 "$(command -v dnsmasq)" --keep-in-foreground --conf-file="$WORK/dhcp.conf"
STAGE=http
printf '\n===== START TEST WEB SERVICE =====\n'
systemd-run --unit="$HTTP" --property=User=nobody --property=RuntimeMaxSec=660 "$(command -v python3)" -c '
from http.server import BaseHTTPRequestHandler, HTTPServer
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = b"Pi Player isolated hotspot test: PASS\n"
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
HTTPServer(("10.42.0.1",18000),Handler).serve_forever()
'
sleep 2
STAGE=service-validation
systemctl is-active "$DHCP.service"
systemctl is-active "$HTTP.service"
ip -br address
ip -4 route
nft list table inet "$TABLE"
STAGE=ready
echo "HOTSPOT READY: pi-player-local / http://10.42.0.1:18000"
printf 'Temporary password (private; do not copy into logs): %s\n' "$PSK" >/dev/tty
unset PSK
echo "Press Enter to clean up, or automatic cleanup after 10 minutes."
read -r -t 600 </dev/tty || true
nft list table inet "$TABLE"
# No client MAC addresses or password printed in diagnostic summary.
if [[ -f "$WORK/leases/dhcp.leases" ]]; then
    echo "DHCP leases: $(wc -l < "$WORK/leases/dhcp.leases")"
else
    echo "DHCP leases: 0"
fi

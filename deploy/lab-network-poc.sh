#!/usr/bin/env bash
# Explicit, temporary lab test only. Never invoked by installation or the API.
set -Eeuo pipefail
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
    set +e
    if [[ $RADIO == 1 ]]; then nmcli radio wifi off; fi
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
# Confirm profile fields before enabling the radio.
[[ $(nmcli -g 802-11-wireless.mode con show uuid "$UUID") == ap ]]
[[ $(nmcli -g 802-11-wireless.ap-isolation con show uuid "$UUID") == yes ]]
[[ $(nmcli -g ipv4.method con show uuid "$UUID") == manual ]]
[[ $(nmcli -g ipv6.method con show uuid "$UUID") == disabled ]]
systemd-run --unit="$SAFETY" --on-active=12min "$(command -v nmcli)" radio wifi off
TIMER=1
RADIO=1
nmcli radio wifi on
nmcli --wait 30 con up uuid "$UUID" ifname wlan0
[[ $(sysctl -n net.ipv4.ip_forward) == 0 && $(sysctl -n net.ipv6.conf.all.forwarding) == 0 ]]
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
systemctl is-active "$DHCP.service"
systemctl is-active "$HTTP.service"
ip -br address
ip -4 route
nft list table inet "$TABLE"
echo "HOTSPOT READY: pi-player-local / http://10.42.0.1:18000"
printf 'Temporary password (private; do not copy into logs): %s\n' "$PSK" >/dev/tty
unset PSK
echo "Press Enter to clean up, or automatic cleanup after 10 minutes."
read -r -t 600 </dev/tty || true
nft list table inet "$TABLE"
# No client MAC addresses or password printed in diagnostic summary.
echo "DHCP leases: $(wc -l < "$WORK/leases/dhcp.leases" 2>/dev/null || echo 0)"

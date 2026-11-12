# Network commissioning — development checkpoint

This is a **lab-only phase 1**, not production-ready wireless management. The
policy module is pure and is not wired to NetworkManager or the API yet.
The explicit hotspot proof of concept is not installed or invoked automatically.
Do not deploy these changes to a production appliance.

## Agreed specification

- Existing and new appliances start with wireless disabled and Ethernet DHCP.
- Ethernet is the exclusive client uplink whenever physical carrier exists.
  Saved Wi-Fi client settings may be staged over Ethernet. Cable reconnection
  must block client traffic before enabling the Ethernet uplink; an event
  callback alone is not sufficient. Unknown carrier must fail closed.
- DHCP client timeout: 30 seconds. When wired DHCP fails, use 10.42.1.1/24
  with duplicate address detection, no DNS or default route. Never override
  deliberate static addressing. Never provide DHCP service on Ethernet.
  Directly attached laptop: 10.42.1.2/24, no gateway or DNS;
  browser http://10.42.1.1:8000. Return to the primary profile when valid DHCP
  is restored; avoid interrupting an active commissioning session.
- Hotspot modes: disabled (default), permanent, recovery. A hotspot and
  Ethernet can coexist, but never a Wi-Fi client and another active uplink.
- Default SSID pi-player-local; configurable to avoid duplicate SSIDs.
  Unique 24-character random password per appliance; no open/shared default
  password. Generate on provisioning/reset; retain across updates. Authenticated
  reveal/change/regenerate via wired setup/settings; no TV display, ordinary
  logs, unauthenticated status, playlist exports or Git. Use direct cable or
  trusted protected management transport for credential retrieval.
- AP: WPA2/RSN AES/CCMP, client isolation, WPS off, IPv6 disabled, address
  10.42.0.1/24. DHCP only while AP active, pool 10.42.0.2–10.42.0.3,
  one-hour lease, no gateway or DNS offered. No bridging, forwarding, NAT.
  Firewall must be verified before activation; local DHCP and explicitly
  allowed management ports only. A two-lease pool is not a security boundary.
- Recovery decisions use local management availability, not Internet access.
  Bound retries and avoid cutting off active recovery sessions.
- Review and restrict application-mediated network access (website content,
  URL preview, system/network actions) before allowing real API access over AP.
  Firewall alone is not sufficient. Consider restricting AP management when
  Ethernet is connected until a safe authorization model is implemented.

## Lab test

On the wired lab Pi, keep playback monitor running in a separate SSH session.
Run the script from a clean development checkout:
  sudo bash deploy/lab-network-poc.sh --hotspot

The script requires ZA regulatory domain, no existing Wi-Fi profile, disabled
radio, active Ethernet carrier, forwarding disabled and no subnet overlap.
It creates a volatile NetworkManager profile, nftables rules, dedicated
dnsmasq and a harmless test HTTP service. The generated password appears only
on the interactive terminal; do not record or share it. It times out and cleans
up; a separate timer disables Wi-Fi if the session fails. If cleanup fails,
leave the isolation firewall installed and investigate locally.

Connect an isolated client, confirm DHCP and test page on port 18000.
Port 8000 and SSH must be blocked. Test an explicitly configured route via
the hotspot address to an authorized test endpoint; absence of a default
route alone does not demonstrate isolation. Inspect firewall counters and
verify Ethernet and playback remain healthy.

Wired fallback must be tested separately using a physically isolated direct
cable and local console or alternate management path. Do not disconnect an
active remote SSH session for the test. No DHCP server on the wired segment.
Automated fallback profile, conflict detection and DHCP retry transitions are
not implemented by this checkpoint.

## Remaining implementation gates

1. Physical AP test, regulatory country persistence and fault cleanup.
2. Ethernet DHCP fallback, conflict detection and restoration; wired/Wi-Fi
   break-before-make interlock, including boot, cable reconnection and failures.
3. Root-owned controller, persistent firewall and isolated DHCP service.
4. Secure credential provisioning/storage/reset and authenticated setup/settings.
5. Recovery mode retries and application-level isolation.
6. Integration tests, reboot and extended soak acceptance before main promotion.

# Network commissioning — development checkpoint

This is a **lab-only development checkpoint**, not production-ready wireless
management. The policy and transition planner are pure and are not wired to
NetworkManager or the API yet.
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
  Unique eight-character random alphanumeric password per appliance (letters
  and digits, mixed case); no open/shared default password. Eight is the
  WPA2 passphrase minimum and is weaker than the original 24-character
  proposal. Permit longer administrator-selected passwords for higher-security
  deployments. Generate on provisioning/reset; retain across updates. Authenticated
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
After Ethernet DHCP has failed on that isolated segment, run from local console:
  sudo bash deploy/lab-ethernet-fallback-poc.sh
The temporary manual profile performs IPv4 duplicate address detection and
uses no default route; it is removed after the test. Automated fallback and
DHCP retry transitions are not implemented by this checkpoint.

## Transition planner (phase 2)

`pi_player/network_controller.py` returns one action per observed snapshot.
It never runs commands or writes network configuration. Its regression tests
cover wired DHCP expiry, fallback conflict handling, unknown carrier,
break-before-make, hotspot isolation and DHCP lifecycle, and bounded recovery
retry. The test command is:

    python3 -m unittest discover -s tests -p 'test_network*.py' -v

The planner uses a proposed five-minute retry interval and defers elective
fallback/client recovery retries unless the actuator can positively establish
that no active commissioning session will be interrupted. It does not infer
network health from Internet connectivity.

### Candidate kernel gates (phase 3)

`pi_player/network_gate.py` renders four complete nftables transactions: closed,
wired-only, client-only, and isolated hotspot. Both owned tables are replaced
atomically. Netdev ingress/egress drops the nonselected interface at frame
level, including ARP, rather than relying on routing metrics. The hotspot
candidate still exposes only the harmless test service on port 18000 and
IPv4 DHCP; forwarding on either managed interface is denied in all modes.
The module also renders the restricted wlan0-only DHCP configuration.

The primitive has no caller in the installed application. Before considering
live use, run the network unit tests, then validate each generated transaction
with `nft -c -f -` on the Pi. Do not use `nft -f -` without the check flag on
an active remote connection: closed/client gates would interrupt Ethernet.
Read-back verification, bridge/namespace checks, reboot ordering, DHCP service
lifecycle and an exclusive root-owned actuator are still required. These
rules do not by themselves prevent a transient Wi-Fi association when a cable
is inserted; their purpose is to prevent simultaneous client data paths.

### Candidate wired actuator (phase 4)

`pi_player/network_actuator.py` provides a read-only runtime observer and
candidate NetworkManager methods for a future locked root-owned service.
Inspection is safe over the active SSH session:

    python3 -m pi_player.network_actuator --inspect

Fallback activation requires the caller to have verified the exclusive wired
gate and 30-second DHCP timeout. The primary profile must be explicitly bound
to eth0, DHCP-only and non-autoconnecting. The actuator refuses a healthy
address, existing default route, unknown carrier, active Wi-Fi radio,
foreign profile, conflicting subnet or existing fallback UUID. It creates an
in-memory fallback profile with duplicate address detection, rechecks before
activation, and verifies the resulting address and route. A failed DHCP retry
attempts to restore the fallback only when the current observations permit it.
Failures must be latched and reconciled by the future controller.

The current lab profile has not been converted to controller ownership.
No CLI for mutation is exposed; the candidate methods are only exercised with
mocked subprocesses. The gate and safe-retry inputs are caller assertions,
not independent proof of kernel state or session absence. Full root service
integration, lock ownership, gate read-back, profile provisioning and actual
isolated-cable acceptance remain mandatory before live use.

### Privileged actuator contract (not integrated)

- Root-owned service and executable outside the application-owned runtime.
  Use fixed validated interfaces/profile UUIDs and a lock around transitions.
  Never execute arbitrary application-supplied commands or source configuration.
- Start with a verified kernel gate; disable independent connection
  autoconnect for the managed profiles. The wired/client data path must be
  mutually exclusive even if NetworkManager receives carrier events before
  the controller. A polling planner alone cannot guarantee this.
- BLOCK_UPLINKS closes both uplink data paths atomically without blocking the
  isolated AP's permitted local traffic. ALLOW_WIRED / ALLOW_CLIENT opens
  only the selected uplink after verifying opposite-role shutdown and fresh
  carrier. START_PRIMARY / START_CLIENT must establish the correct exclusive
  gate for DHCP before activation, then verify the resulting state.
- START_FALLBACK replaces only the managed DHCP primary profile after timeout;
  check overlapping routes and duplicate address detection, never advertise
  DHCP from eth0. RESTORE_PRIMARY removes the fallback and retries DHCP
  with bounded backoff. A failed fallback attempt must latch conflict/failure
  until a fresh permitted retry; do not spin on a failing action.
- INSTALL_HOTSPOT_ISOLATION verifies complete input, output and forwarding
  restrictions (and no forwarding/NAT/bridge). START_HOTSPOT checks them
  again immediately before activating the AP. START_HOTSPOT_DHCP must bind
  to wlan0 and verify AP identity/address; stop it before switching roles.
  RETRY_CLIENT stops AP and verifies DHCP stopped before resetting the
  failure latch. Preserve an active recovery session during elective retries.
- Reconcile observed results after each action; use monotonic timers,
  bounded command timeouts and explicit error state. Recheck facts at action
  execution, not only when planning. Keep the firewall closed on failure.
- No real admin API over the AP until application-mediated OT access is
  reviewed and tested. No auto-enabling service in install/update until
  physical acceptance. The current lab test exposes only port 18000.

## Remaining implementation gates

1. Physical AP test, regulatory country persistence and fault cleanup.
2. Ethernet DHCP fallback, conflict detection and restoration; wired/Wi-Fi
   break-before-make interlock, including boot, cable reconnection and failures.
3. Root-owned controller, persistent firewall and isolated DHCP service.
4. Secure credential provisioning/storage/reset and authenticated setup/settings.
5. Recovery mode retries and application-level isolation.
6. Integration tests, reboot and extended soak acceptance before main promotion.

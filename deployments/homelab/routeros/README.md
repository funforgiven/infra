# Homelab RouterOS Deployment

The CCR2004 is the routed edge. The CRS510 is the 25Gbps server and workstation
fabric. The Omada-managed TP-Link `SG3210XHP-M2` is the copper-to-SFP+
aggregation hop between them.

## Live transition state

State verified on 2026-07-29:

- The CCR staged and activation imports are applied on RouterOS 7.21.5.
- The PPPoE client is running on VLAN 35 over `ether1`.
- The CCR uses `1.1.1.1` as its sole upstream DNS server. Peer DNS from both
  PPPoE and the disabled setup-path DHCP client is ignored.
- The PPPoE username and password were installed over host-key-pinned SSH.
  Their source of truth is now SOPS ciphertext in `secrets/routeros.yaml`;
  sops-nix materializes separate, user-owned `0400` runtime files for the
  installer. Neither value is rendered into an `.rsc`, uploaded as a file,
  passed in a process argument, printed, or stored as plaintext in Git. The
  helper also verifies that RouterOS history did not retain the password
  before writing its nonsecret readiness marker.
- The CCR client VLANs, DHCP servers, NAT, and firewall policies are enabled.
  The input and forward policy hooks are first in their respective chains.
- A temporary untagged legacy LAN is active on `bridge-lan`.
  `192.168.1.1/24`, DNS, DHCP, firewall forwarding, and PPPoE masquerade
  coverage preserve the old LAN during the VLAN migration. The dynamic pool
  `192.168.1.50-.99` had no overlap with any address recorded by Omada when it
  was selected.
- The mistaken direct-TRUSTED `ether15` intermediate state has been retired.
  `bridge10-trusted-access` was removed, and the TRUSTED gateway, DHCP server,
  management policy, and firewall policy terminate on `vlan10-trusted` again.
- `bridge-lan` is the single VLAN-aware CCR LAN bridge. VLAN interfaces 10, 20,
  50, 60, and 90 are parented to it. Its fixed MAC is the original `ether16`
  MAC, so moving the legacy gateway onto the bridge did not change the
  gateway's Layer-2 identity.
- `ether15` and `ether16` remain temporarily configured as hybrid bridge
  ports: native VLAN 1 carries the legacy LAN, while VLANs 10, 20, 50, 60,
  and 90 are tagged. The physical handoff is complete: TP-Link port 1 and the
  main Omada-side clients are learned through `ether15`; the independently
  connected friend-side path remains up on `ether16`.
- Do not narrow `ether16` to untagged-only yet. Its live bridge entries include
  native VLAN 1 and tagged VLANs 10 and 20 from a downstream device. That path
  remains configuration-frozen until its downstream topology is inventoried
  without interrupting the friend using it.
- Both bridge ports deliberately use software forwarding (`hw=no`). This
  avoids reprogramming or resetting their shared switch chip during a
  no-downtime migration. Hardware offload can be enabled later in a maintenance
  window.
- Direct CCR rescue moved from `ether15` to unused `ether8`; its address
  remains `192.168.88.1/24`.
- Temporary DHCP reservations preserve the PC at `192.168.1.197`, the Omada
  switch at `.189`, the AP at `.163`, and the Hue Bridge at `.121`.
- The PiKVM named `ricotta` is currently a dynamic legacy-LAN client at
  `192.168.1.86` with MAC `2C:CF:67:9D:A2:F7`. Omada identifies it on TP-Link
  port 3; the CCR DHCP lease, ARP entry, and successful ping corroborate that
  identity. Its HTTP service redirects to the PiKVM login page; HTTPS port 443
  is not currently listening.
- `sfp-sfpplus1` is disconnected. During the original router cutover, the
  link-state watcher observed the then-active `ether16` handoff and the setup
  SFP+ path down, then disabled the distance-10 DHCP client and removed its
  `INFRA-WAN` membership.
- TP-Link port 1 uses `infra-ccr-trunk` and is connected to CCR `ether15` over
  the existing 20-metre cable. The move was verified from the workstation and
  from the CCR without resetting the PPPoE session.
- Temporary TCP and UDP destination NAT on PPPoE port `25565` targets the PC
  at `192.168.1.197`. The NixOS firewall is already open for both protocols,
  and the Minecraft service was verified listening on both.
- The CRS staged and activation imports are applied on RouterOS 7.21.5.
  Bridge VLAN filtering is enabled. The three server bonds and the PC bridge
  port are enabled but not running: the node cables are connected while the
  nodes are powered off, and the PC endpoint is not connected.
- The CRS uplink and CPU bridge retain untagged VLAN 1 as a temporary recovery
  path. Tagged VLAN 90 management is configured but has not yet been verified
  end to end after the cutover.
- The existing workstation remains on `192.168.1.0/24`, now using the CCR at
  `192.168.1.1` as its default gateway and DNS forwarder. Internet service is
  running over the CCR PPPoE session.
- IPv6 service is not deployed. The CCR has first-position, default-deny IPv6
  input and forward policies, and the raw VLAN-35 transport is part of the WAN
  boundary. Router advertisements are configured off; RouterOS will fully apply
  that setting on its next reboot, while the prior `yes-if-forwarding-disabled`
  state already rejects them because IPv6 forwarding is enabled.

The in-place router replacement is complete. VLAN migration is deliberately
deferred: existing clients remain untagged on `192.168.1.0/24` while the CCR
owns the old gateway address. The old router must not be reconnected to that
legacy LAN while the CCR service is active.

### Legacy LAN inventory

These are the addresses that must remain stable until each endpoint is moved
independently. The first four are RouterOS DHCP reservations; the PiKVM lease
is still dynamic.

| Endpoint | Legacy address | MAC address | Physical location | Lease state |
| --- | --- | --- | --- | --- |
| Primary admin workstation | `192.168.1.197` | `60:CF:84:ED:E9:1E` | TP-Link port 2 | Reserved |
| Omada switch | `192.168.1.189` | `98:25:4A:CB:BF:BE` | TP-Link switch itself | Reserved |
| Omada AP | `192.168.1.163` | `9C:A2:F4:C2:ED:74` | TP-Link port 6 | Reserved |
| Philips Hue Bridge | `192.168.1.121` | `EC:B5:FA:8E:DB:63` | TP-Link port 8 | Reserved |
| PiKVM `ricotta` | `192.168.1.86` | `2C:CF:67:9D:A2:F7` | TP-Link port 3 | Dynamic |

## Network plan

The VLAN ID matches the third octet.

| VLAN | Name | Subnet | Gateway | State and purpose |
| ---: | --- | --- | --- | --- |
| 10 | TRUSTED | `10.21.10.0/24` | `10.21.10.1` | Configured; normal trusted clients |
| 20 | SERVERS | `10.21.20.0/24` | `10.21.20.1` | Configured; nodes, VMs, services, and high-speed PC access |
| 30 | CEPH | `10.21.30.0/24` | None | Configured only on the CRS server bonds; never leaves the CRS |
| 40 | DMZ | `10.21.40.0/24` | Future | Reserved, not configured |
| 50 | IOT | `10.21.50.0/24` | `10.21.50.1` | Configured; IoT and Home Assistant devices |
| 60 | GUEST | `10.21.60.0/24` | `10.21.60.1` | Configured; Internet-only guest clients |
| 70 | LAB | `10.21.70.0/24` | Future | Reserved, not configured |
| 80 | CCTV | `10.21.80.0/24` | Future | Reserved, not configured |
| 90 | MGMT | `10.21.90.0/24` | `10.21.90.1` | Configured; router, switches, APs, IPMI |
| 999 | PARKING | None | None | Reserved for unused ports and invalid native traffic; not configured yet |

VLAN 90 is intentionally static-only: there is no MGMT DHCP pool or server.
The CCR gateway is `10.21.90.1`, and the CRS management address is
`10.21.90.2`. Assign and verify a static address before moving a device such as
the PiKVM to MGMT.

General address allocation:

| Range | Use |
| --- | --- |
| `10.21.<VLAN>.1` | Gateway |
| `10.21.<VLAN>.2-.19` | Network infrastructure |
| `10.21.<VLAN>.20-.99` | Static hosts |
| `10.21.<VLAN>.100-.199` | DHCP |
| `10.21.<VLAN>.200-.239` | VIPs and service addresses |
| `10.21.<VLAN>.240-.254` | Reserved |

The server-specific allocations refine the general convention:

- Servers 1–3 use `10.21.20.10`, `.11`, and `.12`.
- Other physical hosts use `10.21.20.20-.49`.
- VMs and infrastructure use `10.21.20.50-.99`.
- Bootstrap DHCP uses `10.21.20.100-.127`.
- Kubernetes LoadBalancer addresses use `10.21.20.128-.223`.
- Servers 1–3 use `10.21.30.10`, `.11`, and `.12` for Ceph.

WireGuard is reserved as `10.21.100.0/24`. Kubernetes stays outside the LAN
range: pods use `10.244.0.0/16`, and services use `10.96.0.0/12`.

The PC should use VLAN 10 for its default route and Internet, with VLAN 20 as a
direct high-speed path to servers. Each server's 2×25Gbps LACP bond carries
tagged VLANs 20 and 30.

## Firewall and management policy

The CCR accepts established and related traffic, drops invalid traffic, and
ends both the input and forward chains with a default drop. These are the
explicitly allowed new IPv4 flows:

| Source | Allowed destination |
| --- | --- |
| TRUSTED VLAN 10 | Internet, SERVERS VLAN 20, and IOT VLAN 50 |
| Primary admin `10.21.10.20` | CCR SSH/WinBox and MGMT VLAN 90, in addition to normal TRUSTED access |
| SERVERS VLAN 20 | Internet |
| IOT VLAN 50 | Internet |
| GUEST VLAN 60 | Internet |
| MGMT VLAN 90 | Internet |
| Temporary legacy `192.168.1.0/24` | Internet |
| Temporary admin `192.168.1.197` | CCR SSH/WinBox and MGMT VLAN 90, in addition to legacy Internet access |
| WAN | CCR ICMP, established/related replies, and explicitly destination-NATed services only; currently TCP/UDP `25565` to `192.168.1.197` |
| Direct rescue `ether8` | CCR itself from the physically isolated rescue link |

All routed client VLANs and the temporary legacy LAN may use the CCR's DNS
forwarder; DHCP is enabled only where a DHCP server is defined. Other new
inter-VLAN flows are denied. In particular, IOT and GUEST cannot initiate
connections to TRUSTED or SERVERS. CEPH VLAN 30 is switched only by the CRS
and has no CCR gateway.

On both MikroTik devices, SSH and WinBox are the only enabled IP management
services; FTP, Telnet, HTTP, HTTPS, API, and API-SSL are disabled. Neighbor
discovery, the MAC server, and MAC WinBox are restricted to the configured
management interface lists, and MAC ping is disabled. On the CCR those
Layer-2 management interfaces are direct rescue, TRUSTED, and MGMT. On the
CRS they are its bridge transition path, MGMT, and direct rescue. The CRS has
no separate IP firewall in these records, so access to `10.21.90.2` relies on
the CCR policy and VLAN isolation; devices already inside VLAN 90 share its
Layer-2 segment.

IPv6 is not deployed. The CCR input policy permits established traffic,
LAN-side ICMPv6, trusted SSH/WinBox, and direct rescue access. Forwarding
permits established traffic and LAN-side ICMPv6 only; everything else is
dropped, and router advertisements are disabled.

### Remaining security work

- Rotate both temporary MikroTik administrator passwords. Do not store their
  replacements in Git, SOPS alongside unattended network credentials, shell
  history, or chat.
- Split CCR neighbor discovery from MAC-management access. The current
  transition list includes all of VLAN 10, so any TRUSTED endpoint can attempt
  MAC WinBox. Restrict MAC management to direct rescue and MGMT after those
  paths are verified.
- Disable the parent MAC server on both MikroTik devices with
  `allowed-interface-list=none`. That setting controls MAC Telnet and is not
  required for neighbor discovery or the separately scoped MAC WinBox service.
- Remove or narrow the CCR's IPv6 TRUSTED management rule before deploying
  IPv6. It currently permits SSH/WinBox attempts from any VLAN 10 link-local
  address, while the IPv4 rule is correctly restricted to the primary admin
  address list.
- Verify tagged VLAN 90 management to the CRS, then remove its native VLAN 1
  recovery path and the whole `bridge` from `INFRA-MAC-MGMT`. Restrict CRS
  SSH/WinBox source ranges or add an explicit switch input policy at the same
  time; its current transition state relies on VLAN isolation.
- Remove the temporary TCP/UDP `25565` destination NAT as soon as the
  workstation-hosted service moves or stops.
- Inventory the downstream device on CCR `ether16` before removing its tagged
  VLANs. Until then, treat that friend-side path as a transitional trunk, not
  a proven untagged access port.
- Re-adopt the AP into the maintained controller before changing its
  management or SSID VLANs, and retire the legacy LAN only after every
  replacement path has been verified independently.

## Physical map

### CCR2004

| Port | Endpoint and role |
| --- | --- |
| `ether1` | TurkNet ONT; VLAN 35 PPPoE WAN |
| `ether8` | Direct rescue, `192.168.88.1/24` |
| `ether15` | Active TP-Link port 1 hybrid uplink; native legacy LAN plus tagged VLANs 10, 20, 50, 60, and 90 |
| `ether16` | Active friend-side path; preserve its current hybrid configuration until the downstream tagged traffic is inventoried |
| `sfp-sfpplus1` | Disconnected former setup path; do not reconnect while the temporary legacy LAN is active |

The chassis marks `ether15` as `MGMT/BOOT`, but it is a normal RouterOS
Ethernet port after startup and is intentionally used for the Omada uplink.
The label identifies the port used for Netinstall only when the CCR is
deliberately put into Etherboot/recovery mode; it does not reserve the port or
trigger recovery when a switch is connected. The deployed direct-rescue
address has moved to `ether8`. See the
[CCR2004-16G-2S+PC manual](https://help.mikrotik.com/docs/spaces/UM/pages/93552657/CCR2004-16G-2S%20PC)
and [Netinstall documentation](https://help.mikrotik.com/docs/spaces/ROS/pages/24805390/Netinstall).

### TP-Link

This table separates confirmed cabling from observations and inferences. Do
not use an inferred row as a cutover input until its cable endpoint has been
physically confirmed.

| Port | Observed endpoint | Transition role | Confidence |
| ---: | --- | --- | --- |
| 1 | Link up at 1Gbps to CCR `ether15` over the 20-metre cable | Active native legacy VLAN 1 plus tagged deployment VLANs | Endpoint confirmed and live-verified |
| 2 | Link up at 2.5Gbps; current workstation path | Later, untagged VLAN 10 access | Endpoint confirmed |
| 3 | PiKVM `ricotta`; `192.168.1.86`, MAC `2C:CF:67:9D:A2:F7` | Native legacy VLAN 1 during migration; later untagged VLAN 90 management | Confirmed by Omada port data, CCR DHCP/ARP, ICMP, and PiKVM login page |
| 4–5 | Link down | Unused; VLAN 1 only during migration | Observed |
| 6 | Link up at 2.5Gbps with PoE; Omada AP on old controller | Keep current untagged service until its cutover is supervised | Endpoint confirmed |
| 7 | Link down | Unused; VLAN 1 only during migration | Observed |
| 8 | Link up at 100Mbps; Philips Hue Bridge | Later, untagged VLAN 50 access | Endpoint confirmed |
| 9 | Link up at 10Gbps; CRS `sfp28-1` | Tagged VLANs 10, 20, and 90 plus temporary untagged VLAN 1 | Endpoint confirmed and live-verified |
| 10 | Link down; former CCR `sfp-sfpplus1` setup path | Keep disconnected while `bridge-lan` carries the legacy LAN | Endpoint confirmed |

The AP on port 6 remains adopted by its old controller. Re-adoption and SSID
VLAN changes are a separate migration. The temporary CCR legacy LAN preserves
its current untagged management and client network across the router swap, so
AP adoption is not a prerequisite for replacing the router.

The Hue Bridge remains on working VLAN 1 after the swap. It can move
later to the already configured VLAN 50 gateway and DHCP service by assigning
the IoT access profile to port 8.

The PiKVM remains on working VLAN 1 with a dynamic lease. Before assigning
port 3 to VLAN 90, create its intended management address or reservation and
verify that the workstation has a permitted management path to the new
address.

### CRS510

| Port | Endpoint and role |
| --- | --- |
| `sfp28-1` | 10Gbps TP-Link port 9 uplink; VLANs 10, 20, and 90 tagged, temporary VLAN 1 untagged |
| `sfp28-2` | Future PC; VLANs 10 and 20 tagged |
| `sfp28-3` + `sfp28-4` | Server 1 LACP; VLANs 20 and 30 tagged |
| `sfp28-5` + `sfp28-6` | Server 2 LACP; VLANs 20 and 30 tagged |
| `sfp28-7` + `sfp28-8` | Server 3 LACP; VLANs 20 and 30 tagged |
| `ether1` | Direct rescue, `192.168.89.2/24` |

The CCR-to-TP-Link segment is 1Gbps, while the TP-Link-to-CRS link is 10Gbps.
Traffic switched locally by the CRS does not cross the router trunk. A single
server/PC VLAN-20 flow can use up to 25Gbps when the intended NICs are
connected; inter-VLAN traffic is limited to roughly 1Gbps aggregate by the
CCR trunk.

## Omada transition state

The Cloud controller contains L2-only definitions for VLANs 10, 20, 50, 60,
and 90. Omada provides no gateway, SVI, or DHCP service. VLAN 30 and reserved
VLANs 40, 70, 80, and 999 are deliberately absent.

The following explicit profiles exist:

- `infra-vlan1-only`: untagged/native VLAN 1 with configured VLAN tags blocked.
- `infra-ccr-trunk`: untagged/native VLAN 1 and tagged VLANs 10, 20, 50, 60,
  and 90.
- `infra-crs-trunk`: untagged/native VLAN 1 and tagged VLANs 10, 20, and 90.
- `infra-ap-transition`: untagged/native VLAN 1 and tagged VLANs 10, 50, 60,
  and 90; assigned to the old-controller AP during the transition.
- `infra-iot-access`: untagged/native VLAN 50; held for a supervised Hue
  migration after its current legacy path and the replacement access path are
  verified.

Current assignments:

| Port | Current profile | Reason |
| ---: | --- | --- |
| 1 | `infra-ccr-trunk` | Active CCR `ether15` handoff; native legacy VLAN 1 plus tagged deployment VLANs |
| 2 | `infra-vlan1-only` | Confirmed workstation path; explicit temporary VLAN 1 |
| 3 | `infra-vlan1-only` | Preserve PiKVM `ricotta` on the current legacy LAN until its supervised VLAN 90 migration |
| 4–5 | `infra-vlan1-only` | Unused ports |
| 6 | `infra-ap-transition` | Preserve the old-controller AP on native VLAN 1 while allowing the planned AP tags |
| 7 | `infra-vlan1-only` | Unused |
| 8 | `infra-vlan1-only` | Preserve the Hue Bridge on current VLAN 1 |
| 9 | `infra-crs-trunk` | Active CRS trunk with temporary native VLAN 1 |
| 10 | `infra-vlan1-only` | Disconnected former CCR setup path |

Ports 1, 2, and 6 were moved away from Omada's broad `All` profile after their
endpoints were confirmed. Port 1 was then changed to the explicit CCR hybrid
profile, whose native VLAN remains VLAN 1. The Omada switch and public Internet
remain reachable through the CCR after the physical cutover.

The Omada state in this document is observational, not declaratively
reconciled. The repository stores the Omada API connection values as SOPS
ciphertext, but does not materialize them at runtime because there is no
consumer yet. It also cannot apply these profiles or detect controller drift.
Until a narrowly scoped consumer exists, confirm the live Cloud controller
state before every Omada-side change and update this inventory afterward.

No client port needs to move to a deployment VLAN during the router
replacement. Port 2 can migrate to untagged VLAN 10 later. AP management/SSID
VLANs and Hue VLAN 50 are also later, independent migrations.

## Physical cutover state

The physical replacement completed on 2026-07-27:

- TP-Link port 1 is connected to CCR `ether15` with native VLAN 1 and only the
  intended tagged deployment VLANs.
- The TurkNet ONT is connected to CCR `ether1`; `pppoe-turknet` is running.
- The CCR legacy gateway, DHCP, DNS, firewall, NAT, critical-device
  reservations, and temporary Minecraft forwards are active.
- CCR `sfp-sfpplus1` and TP-Link port 10 are disconnected. The watcher disabled
  the former setup DHCP client and removed its `INFRA-WAN` membership.
- The PC remains at `192.168.1.197/24` with gateway and DNS `192.168.1.1`.
- The corrected VLAN-aware `bridge-lan` transition was applied on 2026-07-29.
  The SSH session through `ether16` stayed established, PPPoE stayed connected,
  and the original gateway MAC was preserved. At five probes per second, the
  live transition missed one gateway sample out of 2,671 and one Internet
  sample out of 2,738; both paths resumed on the immediately following sample.
- The supervised Omada uplink move completed on 2026-07-29. The same TP-Link
  port 1 cable moved from CCR `ether16` to `ether15`; the friend-side path
  remained connected to `ether16`.
- Both CCR links negotiated at 1Gbps. The CCR learned the main Omada switch
  and workstation on `ether15`, while distinct friend-side devices remained
  on `ether16`. The workstation kept its legacy address, gateway, DNS, and
  Internet access; management SSH was immediately available through the new
  path.
- PPPoE retained its existing session uptime, and five CCR probes to
  `1.1.1.1` completed without loss after the cable move.

Do not connect both CCR ports to the same Omada switching fabric: parallel
native-VLAN-1 paths can form a Layer-2 loop. Also do not remove tagged VLANs
from `ether16` merely because its intended role is legacy access. Live bridge
learning currently shows VLANs 10 and 20 on that path; inventory the
downstream device and schedule a supervised cleanup before making the port
untagged-only.

Do not repeat the preparation/cutover imports against this live state. If a
physical rollback becomes necessary, first power down the CCR, move both the
20-metre LAN cable and ONT cable back to the old router, and only then power the
old router on. TP-Link port 1's native VLAN 1 remains compatible with that
rollback.

External Minecraft reachability on TCP and UDP `25565` still requires a
publicly reachable TurkNet address. If PPPoE receives CGNAT space, upstream
inbound connections cannot reach the DNAT rules.

The temporary Minecraft forwards intentionally still target `192.168.1.197`.
Change both to `10.21.10.20` only after the PC is independently migrated from
TP-Link port 2 to TRUSTED, the reservation is bound, and Internet reachability
is verified. Moving the Omada uplink to CCR `ether15` does not move the PC to a
new VLAN.

After the CCR is stable, migrate the PC, AP, Hue Bridge, and other clients to
their final VLANs independently. Remove the temporary legacy subnet, DHCP
reservations, cutover script/scheduler, and Minecraft DNAT rules after their
replacement paths are proven.

## Applied records and validation

Router and switch identities have their own directories:

```text
deployments/homelab/routeros/
├── core-router/
│   ├── applied/
│   │   ├── 2026-07-27-factory-bootstrap.rsc
│   │   ├── 2026-07-27-activation.rsc
│   │   ├── 2026-07-27-legacy-lan.rsc
│   │   └── 2026-07-29-lan-bridge-correction.rsc
│   └── install-pppoe.sh
└── core-switch/
    └── applied/
        ├── 2026-07-27-factory-bootstrap.rsc
        └── 2026-07-27-activation.rsc
```

The `.rsc` files are a selected, secret-free archive of one-shot changes that
were successfully applied. The archive is intentionally not a complete or
reproducible migration sequence: it omits the retired, mistaken direct-TRUSTED
intermediate transition that the later LAN-bridge correction removed. The
retained records preserve the meaningful preflight checks and command bodies,
including references to that historical intermediate state.

These are not live desired-state or convergence scripts. Their preconditions
describe states that no longer exist, and each file unconditionally stops at
its first executable line. Do not remove that guard or import an `applied/`
file into either configured device.

Shared validation, credential installation, and tests live under
`components/routeros/`. Run the repository policy checks with:

```sh
components/routeros/validate.sh
```

The validator checks the concrete records, launcher, credential helper, and
tests. It enters the repository development shell itself when its Python
dependencies are not available. RouterOS `dry-run` can check parser syntax on
a controlled reset device, but it is not safe evidence that a historical
record can be replayed against the live router or switch: the record's
preflight may intentionally fail, and any real import could disrupt service.

Install or rotate the PPPoE credentials with:

```sh
deployments/homelab/routeros/core-router/install-pppoe.sh
```

The optional first argument overrides the router host; the default is the
live legacy gateway at `192.168.1.1`. The launcher reads the username and
password from these sops-nix runtime files:

- `/run/secrets/homelab-routeros-pppoe-username`
- `/run/secrets/homelab-routeros-pppoe-password`

Both files are owned by the desktop user and have mode `0400`. The command
prompts separately for the RouterOS login password, verifies the pinned SSH
host-key fingerprint, fails without an interactive terminal, checks RouterOS
history for retained credentials, and only then writes the nonsecret
readiness marker used by the original activation preflight. If the ordinary
Python environment lacks Paramiko, the launcher enters the repository's Nix
development environment itself.

Never put a PPPoE credential or device login password in an `.rsc`, command
argument, log, Nix derivation, or plaintext repository file. Router exports
and binary backups also belong outside this repository.

## Recovery notes

- Direct CCR rescue: connect to `ether8`, configure the client as
  `192.168.88.2/24`, and reach `192.168.88.1`.
- Do not reconnect `sfp-sfpplus1`/TP-Link port 10 while the CCR legacy
  `192.168.1.1/24` service is active on `bridge-lan`; that would create a
  second CCR path into the same broadcast domain.
- Direct CRS rescue: connect to `ether1`, configure the client as
  `192.168.89.3/24`, and reach `192.168.89.2`.
- During the transition, the CRS is also reachable over native VLAN 1 through
  TP-Link port 9. Remove that path only after VLAN 90 works end to end.
- RouterOS Safe Mode over SSH caused SSH service resets and automatic
  `supout.rif` generation on both inspected 7.21.5 devices. Do not rely on a
  remote Safe Mode session as the only rollback mechanism for this deployment;
  keep an on-site direct rescue path and validate each state change explicitly.

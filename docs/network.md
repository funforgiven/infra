# Physical network

The CCR2004 is the routed edge, the CRS510 the 25 Gb/s server fabric, the Omada
SG3210XHP-M2 the copper switch, and two UniFi U7 Pro Max units the access points.
Addresses, MACs, VLAN membership and link policy live in
`deployments/homelab/network/network-inventory.yaml` (RouterOS) and
`omada-network.yaml` (switch); this page covers what those files cannot say.

## Cabling

| Port | Connection |
| --- | --- |
| CCR `ether1` | TurkNet ONT, PPPoE on VLAN 35 |
| CCR `ether8` / CRS `ether1` | direct rescue ports (below) |
| CCR `ether15` | Omada port 1 trunk today; `ether2` is configured identically, move the cable there when recabling |
| CCR `ether3/4` | HOUSEMATE VLAN 70 access ports |
| CCR `ether5` | `u7-pro-max-2` through a UniFi 30 W PoE+ adapter |
| CCR `ether16` | hybrid link awaiting recabling |
| CRS `sfp28-1` | Omada port 9 trunk |
| CRS `sfp28-2` | admin workstation, tagged VLANs 10 and 20 |
| CRS `sfp28-3`..`8` | server bonds, per the inventory |
| Omada ports 2–8 | as commented in `omada-network.yaml` |

Omada port 3 is `gorgonzola` on trusted VLAN 10, as `omada-network.yaml`
declares; older notes placing PiKVM `ricotta` there on VLAN 90 are stale.
`ricotta` is an unused PiKVM v2 that keeps only its address reservation.
`u7-pro-max` on Omada port 6 is pinned to 1 Gb/s because 2.5 Gb/s was unstable
on AP firmware 8.7.11; Omada keeps the speed and owns only the VLAN profile.
`u7-pro-max-2` on CCR `ether5` linked at 1 Gb/s after a cable replacement.

## Wireless

UniFi owns the APs and WLANs (see the UniFi app README); Omada manages only
the switch. The APs take untagged management VLAN 90 from the port PVID with
no VLAN override and get DHCP reservations. `u7-pro-max-2` alone receives DHCP
option 43 pointing at the controller, and the CCR's `unifi` A record resolves
the inform URL after adoption. WLANs are set by hand in the controller (site
"Homelab WiFi", country Turkey, no remote access, no meshing):

- `Rooftrollen`: VLAN 10, 5 and 6 GHz, WPA3-Personal, PMF required, MLO on.
- `Rooftrollen_IoT`: VLAN 50, 2.4 GHz, WPA2-AES, PMF optional, client
  isolation off because local automation needs discovery.

The PSKs are `wireless.psks.personal` and `wireless.psks.iot` in
`secrets/omada.yaml`.

## PiKVM

`burrata` (Omada port 7) drives two chained PiKVM Switch units; unit 1 is next
to the PiKVM. Unit 1 ports `1.1`–`1.4` are `gorgonzola`, `pecorino`, `taleggio`
and `asiago`; unit 2 is unused. API port numbers are zero-based and continuous
across units (`1.1` is 0, `2.1` is 4), and switching ports also moves USB and
virtual media. Only `pecorino` has ATX wiring (API port 1); use physical
buttons elsewhere. Check the active port and screen before sending input.

The web (`admin_password`) and console (`root_password`) passwords are in
`secrets/pikvm-burrata.yaml`; SSH accepts only the administrator key, against
the host key pinned in `ssh-host-keys.json`. Update with `pikvm-update` and
`kvmd-update-switch --do-the-thing` (both units) while physical access is
available.

## Remote access and recovery

- CCR: cable to `ether8`, use `192.168.88.2/24`, reach `192.168.88.1`.
- CRS: cable to `ether1`, use `192.168.89.3/24`, reach `192.168.89.2`.
- Omada: without DHCP it falls back to `192.168.90.5/24` with no gateway.
- Never rely on remote RouterOS Safe Mode: on 7.21.5 entering it can reset SSH.
  Keep a direct rescue path for every management, bridge or firewall change.

`wg-admin` is the infrastructure recovery VPN. It must keep working without
Kubernetes, ZITADEL or NetBird, so its client configs and recovery credentials
live on the admin devices. NetBird is for everyday service access; adding a
NetBird client never adds a RouterOS peer. A new admin device brings its own
public key, gets a SOPS preshared key and a `/32` peer row in the inventory.

The AWS mail relay is also a `wg-admin` peer, but only as a backend: the servers
connect to it, never the reverse. Its new connections are dropped ahead of every
input and forward rule, so a compromised mail host cannot reach the router or
the homelab while replies still flow.

Mullvad carries only trusted-VLAN traffic to OTOTOY's address. The policy rule
uses `lookup-only-in-table`, so when the tunnel is down that traffic is dropped
instead of leaking through the ISP. If OTOTOY's address changes, update the
`/32` and recheck the handshake and the Japanese exit before applying.

## Running the automation

```sh
nix build .#checks.x86_64-linux.homelab-python \
  .#checks.x86_64-linux.homelab-routeros-syntax --no-link --accept-flake-config
cd components/homelab/network-automation
ansible-playbook reconcile-routeros.yaml                    # read-only
ansible-playbook reconcile-routeros.yaml --limit core_switch --tags apply
ansible-playbook reconcile-routeros.yaml --limit core_router --tags apply
```

Apply one device at a time with its rescue port reachable. Narrower tags
(`lan-ports`, `ap-ports`, `lan-peers`, `wan-port-forwards`, `static-leases`,
`unifi-dns`, `private-access`, `mullvad`, ...) mutate only their rows after the
same read-only preflight. The playbook never deletes: remove a row from the
inventory and delete the live object by hand. It requires, but does not
manage, the CRS bridge, the CCR VLAN-90 interface, `allow-remote-requests`, the
final drop rules and the PPPoE masquerade.

The playbook drives the RouterOS CLI over SSH rather than
`community.routeros.api_modify`. Its firewall and NAT rules sit before drop
rules in tables it does not fully own, and `api_modify` can keep order only by
owning (and pruning) a whole table, which risks a lockout that cannot be tested
from here. The local `fahrican.routeros` terminal plugin exists only because
RouterOS 7.21.5 sends a cursor-position query the upstream plugin discards;
recheck it on RouterOS or `community.routeros` upgrades.

Omada plans by default; add `--apply` after reviewing:

```sh
nix run .#sops --accept-flake-config -- decrypt --output-type json secrets/omada.yaml \
  | nix develop --accept-flake-config -c \
      python3 components/homelab/network-automation/omada_reconcile.py --credentials-stdin
```

Device passwords and PPPoE credentials are in `secrets/routeros.yaml`; sops-nix
exposes the login passwords as `0400` files. Rotate a login through the rescue
port or WinBox, one device at a time, then update SOPS. Install PPPoE
credentials on the console; the SOPS copy is the recovery record.

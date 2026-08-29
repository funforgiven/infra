# RouterOS fabric

The CCR2004 is the routed edge and the CRS510 is the 25 Gb/s east-west
fabric. The Omada-managed SG3210XHP-M2 connects copper endpoints and the
CCR/CRS uplinks.

There are two current-state inputs:

- `../cloud/network-inventory.yaml` is the RouterOS inventory: device
  identity, current cloud bonds/VLANs, link policy, provider routing, declared
  static DHCP leases, private cloud DNS forward, WireGuard administration
  routes, and destination-scoped Mullvad egress.
- `components/cloud/network-automation/reconcile-routeros.yaml` is the
  current convergence owner until the RouterOS Terraform import described
  below is complete.

Device exports belong in encrypted backups, not in the desired-state tree.

The cloud network and MTU design lives once in
[`../cloud/README.md`](../cloud/README.md). Omada final state is documented by
its compact desired-state file and reconciler.

## Physical map

| Device | Port | Role |
| --- | --- | --- |
| CCR2004 | `ether1` | TurkNet ONT, VLAN 35 PPPoE |
| CCR2004 | `ether8` | direct rescue, `192.168.88.1/24` |
| CCR2004 | `ether15` | SG3210XHP-M2 port 1 routed trunk |
| CRS510 | `sfp28-1` | SG3210XHP-M2 port 9 routed uplink |
| CRS510 | `sfp28-2` | direct admin workstation; tagged VLANs 10 and 20 |
| CRS510 | `sfp28-3/4` | `bond-server1`, `taleggio` |
| CRS510 | `sfp28-5/6` | `bond-server2`, `asiago` |
| CRS510 | `sfp28-7/8` | `bond-server3`, `pecorino` |
| CRS510 | `ether1` | direct rescue, `192.168.89.2/24` |
| SG3210XHP-M2 | port 3 | PiKVM `ricotta`, MAC `2C:CF:67:9D:A2:F7`; VLAN 90 DHCP reservation `10.21.90.3` |

All qualified server links use forced `25G-baseCR`, RS-FEC (`fec91`),
active/fast 802.3ad, minimum links 1, layer-3+4 hashing, and MTU 9000. Every
individual LACP member has passed supervised failure testing. Cable make/model
is observation, not stable desired identity.

Current reconciliation carries VLAN 20 to the routed/admin uplinks, keeps
VLANs 30–33 on the CRS server bonds, and carries VLAN 40 through Omada ports
1/9 to the CCR provider gateway. VLAN 40 passed every-direction host probes at
MTU 1500, trusted routing, and provider-sourced WAN NAT at the 1492-byte PPPoE
path MTU. The CCR's 1 Gb/s core uplink is not an east-west path.

The CCR desired state contains exactly one split-DNS row: a `FWD` entry for
`cloud.fahrican.com` and all subdomains to the internal CoreDNS service at
`10.21.20.129`. The read-only preflight requires
`allow-remote-requests=yes`; the playbook deliberately does not own that
router-wide setting. Mutation uses the same explicit `apply` tag as the other
CCR resources and proves the row's unique comment, name, type, target,
subdomain match, and enabled state afterward.

Syncthing reaches the primary workstation through Git-owned TCP and QUIC
destination-NAT rules on port `22000`. The target is the workstation's stable
VLAN-10 reservation `10.21.10.20`; the Syncthing GUI is not exposed.

Factorio reaches the services cluster through one Git-owned UDP destination-NAT
rule. WAN port `34197` is forwarded without translation to the dedicated OVN
load-balancer address `10.21.40.123:34197`. A matching destination-specific
forward-filter rule admits only that translated flow; RCON is not forwarded.
The server is published through Factorio's matching service and joining requires
both a verified Factorio account and the shared game password. The automatic
in-game administrator list is empty so privileged operations remain confined to
loopback-only RCON. One UDP-only NAT-reflection rule lets local LAN interfaces
use the same public address and port as WAN players; it matches only a local
non-LAN destination address and does not grant general inter-VLAN access.

## OTOTOY Mullvad egress

The CCR2004 terminates a separate Mullvad WireGuard client interface named
`wg-mullvad-jp`. Only traffic entering from `vlan10-trusted` with destination
`210.135.96.195/32`, the declared address of `ototoy.jp`, uses the
`mullvad-ototoy` routing table and the Osaka `jp-osa-wg-102` exit. DNS and all
other traffic continue through TurkNet. The routing rule uses
`lookup-only-in-table`, so loss of the Mullvad route fails closed instead of
falling back to the direct ISP path.

The Mullvad client private key is a user-owned `0400` sops-nix runtime secret;
only its path, assigned tunnel address, server public key, and public endpoint
are declared in inventory. If OTOTOY's public address changes, update the
inventory destination and requalify DNS, the WireGuard handshake, HTTPS, and
the observed Japanese exit before applying the new `/32`.

## Remote administration

The CCR2004 terminates the split-tunnel `wg-admin` network at
`10.21.91.1/24`, UDP port `51820`, MTU `1420`. It is not added to a trusted
interface list and is not NATed toward the internet. Firewall rules allow only
DNS on the CCR, SSH to the three cloud hosts, HTTPS to the private and personal
services Gateways, the undercloud and CAPI Kubernetes APIs, and the declared
management ports for the CCR, CRS, PiKVM, EAP, and Omada switch.

Each administrator device supplies its own WireGuard public key and receives a
unique SOPS-encrypted preshared key. Add the public key and sops-nix runtime
path under `routeros_wireguard.peers` in `network-inventory.yaml`, using a
unique `/32` from `10.21.91.0/24`; never commit the client private or preshared
key as plaintext. A client routes only `10.21.20.0/24`, `10.21.40.100/32`,
`10.21.40.122/32`, `10.21.90.0/24`, and `10.21.91.1/32` through the tunnel and
uses `10.21.91.1` for private DNS. The stable `10.21.40.122` services Gateway
fronts every personal service hostname, so publishing another application on
that Gateway does not require another WireGuard route or firewall rule.

## Current reconciliation

Enter the repository shell and validate the standard Ansible/YAML/Python
surfaces:

```sh
nix develop --accept-flake-config
cd components/cloud/network-automation
python3 -m unittest discover -s tests -p 'test_*.py' -v
ansible-playbook --syntax-check reconcile-routeros.yaml
```

The default run is read-only:

```sh
ansible-playbook reconcile-routeros.yaml
```

`--tags apply` enables writes. Apply one device at a time with its
direct rescue path available:

```sh
ansible-playbook reconcile-routeros.yaml --limit core_switch --tags apply
ansible-playbook reconcile-routeros.yaml --limit core_router --tags apply
```

Use `--limit core_router --tags mullvad` to select only the destination-scoped
Mullvad objects while retaining the standard read-only CCR preflight.
Use `--limit core_router --tags wan-port-forwards` to reconcile only the
declared Factorio WAN/reflection and Syncthing destination-NAT rows after the
usual preflight.

The playbook owns only the inventory-declared subset. It does not infer unknown
cabling or rewrite unrelated dynamic leases. Static lease activity is not
configuration, so an offline workstation or Hue Bridge does not create false
drift.

VLAN 90 reserves `10.21.90.3` for PiKVM `ricotta` through a CCR2004 static
DHCP lease on a static-only management DHCP server; no dynamic management pool
exists. The SG3210XHP-M2 uses the same model at `10.21.90.5`. Omada port 3 is
an untagged VLAN-90 access port, so PiKVM needs no host-side VLAN configuration.
The switch's sole management interface uses VLAN 90 and DHCP; its previous
management interface is disabled. If DHCP is unavailable, its direct-recovery
address is `192.168.90.5/24` with no gateway.

RouterOS 7.21.5 sends terminal-position queries that the upstream Ansible
terminal filter discards. The small source-local terminal adapter answers that
observed negotiation while retaining `community.routeros.command`. Delete the
adapter together with this Ansible owner after the REST provider import.

## Omada reconciliation

The Omada adapter plans by default. It receives the API credential on standard
input from SOPS:

```sh
set -o pipefail
nix run .#sops --accept-flake-config -- \
  decrypt --output-type json secrets/omada.yaml \
  | nix develop --accept-flake-config -c \
      python3 components/cloud/network-automation/omada_reconcile.py \
      --credentials-stdin
```

After reviewing the plan, add `--apply`. Creating an SSID or intentionally
rotating its PSK also requires `--include-write-only`, because the controller
does not return stored PSKs. The adapter never deletes controller objects.

## Secrets and identity

Device passwords and PPPoE credentials are SOPS ciphertext in
`secrets/routeros.yaml`. sops-nix exposes only narrow `0400` runtime files.
The Ansible inventory contains secret paths, never passwords. Nix renders the
public keys in `../ssh-host-keys.json` into the standard system known-hosts file;
Ansible/libssh checks it and cannot auto-enrol a replacement key.

Rotate a RouterOS login through direct console or WinBox, one device at a
time, then update its SOPS value before running automation. PPPoE credential
installation remains a supervised console/WinBox bootstrap step until the
secure Terraform import wave; the encrypted values in Git are the recovery
source. Do not pass them on a command line or add a bespoke credential helper.

## Recovery

- CCR: connect directly to `ether8`, use `192.168.88.2/24`, and reach
  `192.168.88.1`.
- CRS: connect directly to `ether1`, use `192.168.89.3/24`, and reach
  `192.168.89.2`.
- Do not use remote RouterOS Safe Mode as the only rollback path; the qualified
  version can reset SSH and generate support output when it is entered.
- Keep a direct rescue or console path for every management, REST, bridge, or
  firewall change.

# RouterOS fabric

The CCR2004 is the routed edge and the CRS510 is the 25 Gb/s east-west
fabric. The Omada-managed SG3210XHP-M2 connects copper endpoints and the
CCR/CRS uplinks.

There are two current-state inputs:

- `../cloud/network-inventory.yaml` is the RouterOS inventory: device
  identity, current cloud bonds/VLANs, link policy, provider routing, declared
  static DHCP leases, private cloud DNS forward, and WireGuard administration
  boundary.
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

## Remote administration

The CCR2004 terminates the split-tunnel `wg-admin` network at
`10.21.91.1/24`, UDP port `51820`, MTU `1420`. It is not added to a trusted
interface list and is not NATed toward the internet. Firewall rules allow only
DNS on the CCR, SSH to the three cloud hosts, HTTPS to the two private Gateway
VIPs, the undercloud and CAPI Kubernetes APIs, and the declared management
ports for the CCR, CRS, PiKVM, EAP, and Omada switch.

Each administrator device supplies its own WireGuard public key and receives a
unique SOPS-encrypted preshared key. Add the public key and sops-nix runtime
path under `routeros_wireguard.peers` in `network-inventory.yaml`, using a
unique `/32` from `10.21.91.0/24`; never commit the client private or preshared
key as plaintext. A client routes only `10.21.20.0/24`, `10.21.40.100/32`,
`10.21.90.0/24`, and `10.21.91.1/32` through the tunnel and uses `10.21.91.1`
for private DNS.

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

`--tags apply` is the mutation boundary. Apply one device at a time with its
direct rescue path available:

```sh
ansible-playbook reconcile-routeros.yaml --limit core_switch --tags apply
ansible-playbook reconcile-routeros.yaml --limit core_router --tags apply
```

The playbook owns only the inventory-declared subset. It does not infer unknown
cabling or rewrite unrelated dynamic leases. Static lease activity is runtime
evidence, not desired state, so an offline workstation or Hue Bridge does not
create false drift.

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

## Terraform adoption

Use the
[`terraform-routeros/routeros`](https://github.com/terraform-routeros/terraform-provider-routeros)
provider as the permanent RouterOS owner. It has
native resources for the bonds, bridge ports/VLANs, addresses, DHCP leases,
firewall/NAT, DNS, certificates, and users used here. Do not add HCL before it
can be tested against imported live objects; unimported declarations could
attempt to create duplicates.

The adoption is one controlled maintenance wave:

1. Export and independently back up both devices and record their current
   RouterOS resource IDs.
2. Create a dedicated internal CA and least-privilege automation user. Enable
   RouterOS HTTPS/REST only on management/rescue interfaces; plain HTTP and
   `insecure = true` are forbidden.
3. Pin the provider exactly and keep its credentials in SOPS. Never commit a
   plan file or pass a password in an argument.
4. Store state outside Git in an encrypted, backed-up location. HCL remains
   desired state; Terraform state is replaceable reconciliation metadata, but
   losing it turns every resource back into an import operation.
5. Import every object before its first plan. Require a zero-change plan,
   then test one harmless comment drift and restoration on each device.
6. Move ownership by complete resource class—leases, then CRS bonds/VLANs,
   then CCR DNS/firewall—not by having Ansible and Terraform manage the same
   object simultaneously.
7. After a full no-op plan and rescue test, remove the RouterOS Ansible
   playbook, terminal adapter, inventory connection fields, and their tests.

This adoption sequence produces one replacement owner, never two permanent
controllers.

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

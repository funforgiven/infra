# Physical network automation

This component contains the RouterOS Ansible playbook and the Omada API
adapter. Both read desired state from `deployments/homelab/network/` and default
to inspection only. The physical map, apply commands, and rescue paths are in
the [RouterOS runbook](../../../deployments/homelab/routeros/README.md).

Neither tool owns firmware upgrades, device resets, adoption, or controller
objects absent from its input.

## RouterOS

`reconcile-routeros.yaml` consumes `network-inventory.yaml` and manages:

- CRS server bonds, bridge ports, and VLANs 20, 30, 40 and 50;
- server-port speed, FEC, LACP, and MTU settings;
- CCR bridge VLAN membership, parallel migration trunks on ports 2/15, and
  HOUSEMATE VLAN 70 with DHCP and internet access on ports 3/4;
- the direct UniFi AP hybrid port on CCR port 5: native management VLAN 90
  and tagged WLAN VLANs 10/50;
- Steam transfers and discovery in both directions between HOUSEMATE VLAN 70
  and TRUSTED VLAN 10;
- the VLAN-90 management DHCP server, declared static leases, and lease-scoped
  UniFi controller discovery through DHCP option 43;
- the private `cloud.fahrican.com` DNS forward and exact `unifi` controller A record;
- the `wg-admin` interface and its limited firewall rules;
- the Mullvad route used only for OTOTOY from trusted VLAN 10;
- the Factorio/Valheim UDP and Syncthing TCP/QUIC destination NAT and matching
  destination-specific forward-filter rules;
- the Factorio provider-to-WAN UDP discovery source-port pin, ordered before
  the generic PPPoE masquerade; and
- the VLAN-40 provider gateway and related forwarding/NAT rules.

The CRS bridge, the CCR VLAN-90 interface/address, and
`allow-remote-requests=yes` must already exist. The playbook checks those
prerequisites but does not manage them. Removing an item from inventory does
not delete the corresponding live RouterOS object.

Passwords and WireGuard private keys are read from user-owned mode-`0400`
sops-nix files. Public host keys come from
`deployments/homelab/ssh-host-keys.json`; automatic SSH host-key enrollment is
disabled.

RouterOS 7.21.5 sends a terminal-position query discarded by the upstream
Ansible terminal filter. The local `fahrican.routeros` adapter handles only
that negotiation and delegates everything else to the pinned upstream plugin.

Run the component tests and syntax check with:

```sh
nix build .#checks.x86_64-linux.homelab-python \
  .#checks.x86_64-linux.homelab-routeros-syntax \
  --no-link --accept-flake-config
```

## Omada

`omada_reconcile.py` consumes `omada-network.yaml`. It manages the declared
switch-only networks, profiles and port assignments for the exact configured
site and switch. The version-2 `scope: switch-only` input never reads or mutates
AP/WLAN objects and works with the unplugged EAP670. UniFi now owns WLANs;
see the [AP migration runbook](../../../deployments/homelab/cluster/apps/unifi/README.md). The controller UI still
owns the switch management interface because the public API does not expose it.

The adapter:

- accepts credentials only as JSON on standard input;
- requires HTTPS and the system trust store;
- refuses redirects and deletion;
- plans by default; and
- polls readable state after a write.

Use `--apply` only after reviewing the plan. Legacy version-1 inputs retain
SSID support and require `--include-write-only` for write-only PSKs; the active
switch-only input does not access those credentials or configure SSIDs.
The exact commands live in the RouterOS runbook so credential handling is
documented in one place.

If either tool is replaced by an OpenTofu provider, import and verify every
existing object before changing ownership. Do not let the old and new tools
manage the same resource at the same time.

## Legacy network retirement

The target inventory excludes Nova migration VLAN 31, OVN/Geneve VLAN 32 and
Manila/NFS VLAN 33, and removes old CAPI/workload/cloud API permissions. Those
objects remain listed under explicit retirement inventory, because dropping
desired rows alone does not delete existing RouterOS objects. The separate
`retire-legacy` tag checks exact captured object identity and refuses conflicting
rows. It requires `migration_exports_verified=true`, after the final independent
exports and source recovery archives have been verified. Normal `apply` does
not select these deletion tasks. Use the command and sequencing in the
[migration runbook](../../../docs/migration/RUNBOOK.md).

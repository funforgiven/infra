# Cloud network automation

This component contains the RouterOS Ansible playbook and the Omada API
adapter. Both read desired state from `deployments/homelab/cloud/` and default
to inspection only. The physical map, apply commands, and rescue paths are in
the [RouterOS runbook](../../../deployments/homelab/routeros/README.md).

Neither tool owns firmware upgrades, device resets, adoption, or controller
objects absent from its input.

## RouterOS

`reconcile-routeros.yaml` consumes `network-inventory.yaml` and manages:

- CRS server bonds, bridge ports, and VLANs 20, 30–33, and 40;
- server-port speed, FEC, LACP, and MTU settings;
- the VLAN-90 management DHCP server and declared static leases;
- the private `cloud.fahrican.com` DNS forward;
- the `wg-admin` interface and its limited firewall rules;
- the Mullvad route used only for OTOTOY from trusted VLAN 10;
- the Factorio UDP and Syncthing TCP/QUIC destination NAT and matching
  destination-specific forward-filter rules; and
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
nix build .#checks.x86_64-linux.cloud-python \
  .#checks.x86_64-linux.cloud-ansible \
  --no-link --accept-flake-config
```

## Omada

`omada_reconcile.py` consumes `omada-network.yaml`. It manages the declared
switch-only networks, profiles, port assignments, and `Rooftrollen` SSIDs for
the exact configured site, switch, and access point. The controller UI still
owns the switch management interface because the public API does not expose it.

The adapter:

- accepts credentials only as JSON on standard input;
- requires HTTPS and the system trust store;
- refuses redirects and deletion;
- plans by default; and
- polls readable state after a write.

Use `--apply` only after reviewing the plan. Creating an SSID or rotating a PSK
also requires `--include-write-only`, because Omada cannot return stored PSKs.
The exact commands live in the RouterOS runbook so credential handling is
documented in one place.

If either tool is replaced by an OpenTofu provider, import and verify every
existing object before changing ownership. Do not let the old and new tools
manage the same resource at the same time.

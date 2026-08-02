# Cloud network automation

The current physical network has one desired-state owner per device family:

- Ansible reconciles the Git-declared RouterOS subset.
- `omada_reconcile.py` is the narrow compatibility adapter for the Omada
  OpenAPI resources in `omada-network.yaml`.

Both default to read-only inspection. Neither owns firmware upgrades, device
resets, adoption, or undeclared controller objects.

## RouterOS

`deployments/homelab/cloud/network-inventory.yaml` is the input to
`reconcile-routeros.yaml`. The playbook currently owns:

- CRS510 server bonds `bond-server1` through `bond-server3`;
- their bridge ports and VLANs 20 and 30–32;
- the observed E810/DAC 25 GbE/RS-FEC policy on all server-member ports;
- the static-only VLAN-90 management DHCP server and network; and
- the inventory-declared CCR2004 static leases; and
- the single private-zone DNS forward from `cloud.fahrican.com` to the
  internal CoreDNS VIP `10.21.20.129`.

The CRS bootstrap must already provide one enabled VLAN-filtering bridge named
`bridge`. Manila VLAN 33 and external VLAN 40, including the latter's Omada
port 1/9 transit and CCR gateway/firewall, belong to later service waves. They
are intentionally absent from current reconciliation so a partial path cannot
be created.
The CCR bootstrap must already provide the enabled `vlan90-mgmt` interface and
its `10.21.90.1/24` address. The future RouterOS Terraform import takes ownership
of both bootstrap substrates.
RouterOS must already have `allow-remote-requests=yes`; this reconciler asserts
that prerequisite but does not take ownership of the router-wide DNS setting.
Current reconciliation creates or updates its declared objects; omission alone
never deletes a live object. Terraform replaces this boundary after import.

Use the flake-locked environment and run the local checks before a maintenance
window:

```sh
nix develop --accept-flake-config
cd components/cloud/network-automation
python3 -m unittest discover -s tests -p 'test_*.py' -v
ansible-playbook --syntax-check reconcile-routeros.yaml
ansible-playbook --list-tasks --tags apply reconcile-routeros.yaml
```

The ordinary run reads and displays current state:

```sh
ansible-playbook reconcile-routeros.yaml
```

Mutation is explicitly tagged and performed one device at a time with its
direct rescue path available:

```sh
ansible-playbook reconcile-routeros.yaml --limit core_switch --tags apply
ansible-playbook reconcile-routeros.yaml --limit core_router --tags apply
```

Credential loading and semantic preflight tasks are tagged `always`. Apply
paths assert the link, VLAN, lease, and private DNS objects for which the
playbook defines exact postconditions. Carrier, LACP member failure, MTU, and
end-to-end traffic are separate supervised qualifications; all three current
hosts and all six LACP members have passed them.

Each device login password is read from its user-owned `0400` sops-nix file
immediately before the first connection. Inventory contains only the runtime
path. Do not pass credentials in arguments, inventory, or environment
variables.

SSH identity has one authority: public keys in
`deployments/homelab/ssh-host-keys.json`. The NixOS
`homelab-management` module renders them into `/etc/ssh/ssh_known_hosts`;
libssh host-key checking is enabled and automatic enrollment is disabled.

RouterOS 7.21.5 sends a terminal-position query that the upstream Ansible
terminal filter discards. The source-local `fahrican.routeros` adapter handles
that observed negotiation and otherwise redirects to the pinned upstream
RouterOS implementation. Delete the adapter, playbook, and their tests after
the RouterOS Terraform import is complete.

## Omada

`omada_reconcile.py` validates the exact `Hark` site, switch, and EAP670
identities. It owns only the profiles, port assignments, and `Rooftrollen`
SSIDs declared in `deployments/homelab/cloud/omada-network.yaml`.
The same file records the switch management interface, which remains a
controller-UI setting because the public OpenAPI does not expose it.
`wireless.policy: standard` expands to the one qualified WPA2/AES policy.

The default command plans without changing the controller:

```sh
set -o pipefail
nix run .#sops --accept-flake-config -- \
  decrypt --output-type json secrets/omada.yaml \
  | nix develop --accept-flake-config -c \
      python3 components/cloud/network-automation/omada_reconcile.py \
      --credentials-stdin
```

After review, apply readable state with `--apply`. SSID creation or an
intentional password rotation additionally requires `--include-write-only`
because Omada does not return stored PSKs:

```sh
set -o pipefail
nix run .#sops --accept-flake-config -- \
  decrypt --output-type json secrets/omada.yaml \
  | nix develop --accept-flake-config -c \
      python3 components/cloud/network-automation/omada_reconcile.py \
      --credentials-stdin --apply --include-write-only
```

The adapter requires a credential-free HTTPS origin, validates TLS with the
system trust store, refuses redirects and deletes, accepts secrets only on
standard input, and polls readable state after writes. Its interface contract
is the [Omada Open API documentation](https://omada-northbound-docs.tplinkcloud.com/).

Freeze this adapter's scope. The `emanuelbesliu/tplink-omada` Terraform
provider is the preferred whole replacement once Controller 6.x behavior,
TLS, imports, and a dedicated least-privilege local username/password pass
local qualification. The provider does not currently consume the existing
OpenAPI client ID/secret. Do not run both owners for the same resource.

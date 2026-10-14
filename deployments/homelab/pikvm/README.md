# PiKVM management

The two PiKVMs have separate identities and credentials. Check the Ethernet
MAC before any enrollment, network change, or recovery operation.

| Device | Management address | Ethernet MAC | Omada port |
| --- | --- | --- | --- |
| `ricotta` | `10.21.90.3` | `2C:CF:67:9D:A2:F7` | 3 |
| `burrata`, PiKVM V4 Plus | `10.21.90.8` | `88:A2:9E:41:73:2C` | 7 |

Both network ports use untagged management VLAN 90. Addresses are static
DHCP reservations on the CCR2004; the PiKVMs retain ordinary DHCP and need no
host-side VLAN configuration. The RouterOS and Omada desired state lives in
`../network/network-inventory.yaml` and `../network/omada-network.yaml`.

Management DNS belongs to the cluster's CoreDNS zone in
`../cluster/infrastructure/dns/dns.yaml`, reconciled by the `dns` Flux stage
from signed `main` commits. The `burrata.mgmt` record is declared there.
The old `wave37-service-network` owner was retired with OpenStack; use the
current `dns` stage when checking reconciliation.

## Access to burrata

Use `https://10.21.90.8/` or
`https://burrata.mgmt.cloud.fahrican.com/`. The web username is `admin`.
HTTPS uses the device's self-signed certificate. Only the existing admin
workstation and the infrastructure WireGuard recovery path have management
access. The WireGuard rule admits TCP 22 and 443 to this device.

The web password and Linux root console recovery password are separate,
random values encrypted in `../../../secrets/pikvm-burrata.yaml`. Retrieve
the web password locally with:

```sh
nix run .#sops --accept-flake-config -- decrypt \
  --extract '["pikvm"]["admin_password"]' secrets/pikvm-burrata.yaml
```

Use `root_password` instead of `admin_password` for console recovery. Do not
copy either plaintext password into the repository.

SSH uses the existing administrator key at `/run/secrets/github-ssh-key`:

```sh
ssh -i /run/secrets/github-ssh-key root@10.21.90.8
```

The `burrata` SSH alias is declared in the workstation's Nix configuration.
After deploying that configuration, `ssh burrata` selects the same key and
address. The device's ED25519 host key is pinned in `../ssh-host-keys.json`;
its fingerprint is `SHA256:sLW3LhYyjJDAsSMK3KNbZjlYyvAOS1xYicO6PeMqwNg`.
The same public key is installed in the workstation user's `known_hosts` for
immediate access. SSH password and keyboard-interactive authentication are
disabled in `/etc/ssh/sshd_config.d/10-infra-key-access.conf`; root login uses
`PermitRootLogin prohibit-password`. The root password remains available for
console recovery.

Enrollment on 2026-10-12 updated KVMD to `4.225`, the kernel to
`6.12.105-2-rpi`, and both switch units to firmware `9`. The hostname and web
metadata identify this device as `burrata`; its timezone is `Europe/Istanbul`.

## Two-switch chain

`burrata` has two official PiKVM Switch Multiport Extenders, with four ports
per unit. Unit 1 is closest to the PiKVM; unit 2 connects to unit 1's
DOWNLINK connectors. The web interface exposes ports `1.1`–`1.4` and
`2.1`–`2.4`. Port names remain unset until the target machines are connected.

Target computers were not connected during initial enrollment. HDMI video,
USB input, boot media, and ATX power control must be qualified after cabling.
Both units and selection of all eight ports passed verification; port `1.1`
is selected initially.
For each computer, the official switch guide specifies:

- One HDMI 2.0 cable, at least 50 cm long.
- One USB-A to USB-C cable supporting data, for the switch's host USB port.
- One straight Ethernet patch cable when using the supplied ATX board for
  motherboard power and reset control. The ATX connector connects to the
  supplied motherboard board, not to an Ethernet network port.

Follow the [official switch wiring guide](https://docs.pikvm.org/switch/)
for the PiKVM UPLINK, inter-switch DOWNLINK, and shared 12 V power cabling.
Once a computer is connected, label its exact unit/port, confirm video and
keyboard/mouse input, then qualify boot media and any wired ATX controls.

## Maintenance

Use the [official updater](https://docs.pikvm.org/faq/#first-steps) for OS
updates while physical access is available:

```sh
ssh burrata
pikvm-update
```

When the switch interface reports a firmware update, use the
[official switch update procedure](https://docs.pikvm.org/switch/#firmware-updating):

```sh
kvmd-update-switch --do-the-thing
```

The updater applies firmware to both chained switch units. Verify both units
and all eight ports afterward. Preserve the default read-only root filesystem
and the switch's persistent storage at `/var/lib/kvmd/pst`.

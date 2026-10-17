# PiKVM management

`burrata` is the PiKVM in use; `ricotta` is an unused PiKVM v2 that keeps its
address reservation. Their identities and credentials are separate. Check the
Ethernet MAC before enrollment, network changes or recovery.

| Device | Management address | Ethernet MAC | Omada port |
| --- | --- | --- | --- |
| `ricotta` | `10.21.90.3` | `2C:CF:67:9D:A2:F7` | 3 |
| `burrata`, PiKVM V4 Plus | `10.21.90.8` | `88:A2:9E:41:73:2C` | 7 |

Both network ports use untagged management VLAN 90. Addresses are static
DHCP reservations on the CCR2004; the PiKVMs use ordinary DHCP and need no
host-side VLAN configuration. The RouterOS and Omada desired state lives in
`../network/network-inventory.yaml` and `../network/omada-network.yaml`.

Management DNS belongs to the cluster's CoreDNS zone in
`../cluster/infrastructure/dns/dns.yaml`, reconciled by the `dns` Flux stage
from signed `main` commits. The `burrata.mgmt` record is declared there.

## Access to burrata

Use `https://10.21.90.8/` or
`https://burrata.mgmt.cloud.fahrican.com/`. The web username is `admin`.
HTTPS uses the device's self-signed certificate. Only the admin
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

SSH uses the administrator key at `/run/secrets/github-ssh-key`:

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
`PermitRootLogin prohibit-password`. The root password is for console recovery.

Hostname `burrata`, timezone `Europe/Istanbul`.

## Two-switch chain

`burrata` has two official PiKVM Switch Multiport Extenders, with four ports
per unit. Unit 1 is closest to the PiKVM; unit 2 connects to unit 1's
DOWNLINK connectors. The web interface exposes ports `1.1`–`1.4` and
`2.1`–`2.4`. The unit-1 mapping is:

| Port | Computer | CPU |
| --- | --- | --- |
| `1.1` | `gorgonzola`, GMKtec NucBox K8 Plus, Windows 11 Pro | Ryzen 7 8845HS |
| `1.2` | `pecorino`, Kubernetes | Core i9-14900K |
| `1.3` | `taleggio`, Kubernetes | Core i5-13600K |
| `1.4` | `asiago`, Kubernetes | Ryzen 9 9900X |

Unit 2 is unused. Check current HDMI and USB attachment through the switch API;
the table describes the intended wiring. A detected HDMI connection alone does
not establish that a host is running or producing video. The
[server hardware inventory](../../../components/nix/servers/README.md#hardware-identity)
distinguishes verified hardware from recorded values. There are no ATX
connections, so PiKVM cannot physically power-cycle these PCs. Check the active
port and visible hardware identity before attaching media or sending input.
For each computer, the official switch guide specifies:

- One HDMI 2.0 cable, at least 50 cm long.
- One USB-A to USB-C cable supporting data, for the switch's host USB port.
- One straight Ethernet patch cable when using the supplied ATX board for
  motherboard power and reset control. The ATX connector connects to the
  supplied motherboard board, not to an Ethernet network port.

Follow the [official switch wiring guide](https://docs.pikvm.org/switch/)
for the PiKVM UPLINK, inter-switch DOWNLINK, and shared 12 V power cabling.
Once a computer is connected, label its exact unit/port, confirm video and
keyboard/mouse input, then test boot media and any wired ATX controls.

## Operating a host through the API

The [HTTP API](https://docs.pikvm.org/api/) works over HTTPS with the web
credentials; keep them out of command arguments and output.

- `POST /api/switch/set_active?port=N` selects a switch port. `N` is zero-based
  and continuous across units (`1.1` is 0, `2.1` is 4). Switching ports also
  moves USB and virtual media, so stay on a host while it boots from media.
- `GET /api/streamer/snapshot` returns a fresh screenshot. Wait for the switch
  and USB devices to settle after changing ports.
- `/api/hid/events/send_key`, `/api/hid/events/send_shortcut` and
  `/api/hid/print` send keys and text. Match the host's keyboard layout and
  check the screen after input.
- `/api/msd/write` uploads an ISO, `/api/msd/set_params` selects it and
  `/api/msd/set_connected` attaches it. Verify the ISO checksum first.

Without ATX wiring, a powered-off or frozen host needs a physical button press.

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
and all eight ports afterward. Keep the default read-only root filesystem
and the switch's persistent storage at `/var/lib/kvmd/pst`.

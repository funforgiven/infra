# UniFi access points

UniFi owns only the APs and WLAN configuration. The CCR2004 keeps routing,
DHCP, DNS, firewall policy and WireGuard; the CRS and the Omada switch keep
switching. MikroTik replacement switches must carry the same VLAN trunk. Omada
stays in service until its last switch is replaced. Its reconciler uses
`scope: switch-only`, so an offline AP cannot block switch maintenance.

The native UniFi OS Server runs in one supported Ubuntu 24.04 KubeVirt guest:
2 vCPU and 4 GiB RAM. The guest disk is `disk.img` inside the 80 GiB
`unifi-root` filesystem-mode RBD claim. It holds the native UOS data, owner,
private CA, timers and AP adoption. A controller outage leaves adopted APs
forwarding their last configuration while management and telemetry are
unavailable. The guest has a masquerade management NIC and a direct VLAN-40
bridge NIC with the address `10.21.40.127`.

Ubiquiti recommends [UniFi OS Server](https://help.ui.com/hc/en-us/articles/34210126298775-Self-Hosting-UniFi)
for new self-hosted installations; it requires host services and is not packaged
as an official standalone Kubernetes container.

## Addresses and ownership

| Purpose | Address or configuration |
| --- | --- |
| Private browser access | `https://unifi.fahrican.com` through Envoy `10.21.40.122` |
| Controller VM | `10.21.40.127`, direct VLAN-40 guest address |
| AP inform endpoint | `http://10.21.40.127:8080/inform` |
| Native inform DNS | Local `unifi` A record resolves to `10.21.40.127`; new AP uses `http://unifi:8080/inform` |
| AP STUN | `10.21.40.127:3478/udp` |
| U7 Pro Max | `74:F9:2C:3C:99:F7`, DHCP reservation `10.21.90.6` |
| Physical attachment | SG3210XHP-M2 port 6, `infra-ap-trunk` |
| Second U7 Pro Max | `U7 Pro Max 2`, `A4:F8:FF:8E:53:5C`, DHCP reservation `10.21.90.7`; adopted |
| Second AP attachment | CCR2004 `ether5` through a UniFi 30 W PoE+ adapter; 1 Gb/s full duplex |
| Ethernet speed | Port 6 fixed at 1 Gb/s (2.5 Gb/s unstable on this path) |
| AP management | Untagged at the AP, switch PVID/native VLAN 90 |
| Trusted WLAN | `Rooftrollen`, tagged VLAN 10, 5/6 GHz, WPA3 with required PMF and MLO |
| IoT WLAN | `Rooftrollen_IoT`, tagged VLAN 50, 2.4 GHz, WPA2-AES |

The router's management DHCP service is **static-only**. A replacement AP needs
its own verified Ethernet MAC reservation before it can receive an address.
Do not enable a general DHCP pool. Do not set a VLAN 90 management override
on the U7: its management traffic is untagged on this switch port.

The second AP uses the same VLANs directly on CCR2004 `ether5`: PVID/native
VLAN 90 and tagged VLANs 10/50. Connect `ether5` to the adapter's LAN/Data In
socket and its PoE Out socket to the AP. Its static reservation receives DHCP
option 43 (`01040a15287f`), pointing to the inform endpoint without a manual
`set-inform`; the router's `unifi` DNS record keeps that address stable. Its
channels are 6 on 2.4 GHz, 100 on 5 GHz and 37 on 6 GHz. Channel 100 is DFS
and waits for its radar check at startup. Wireless meshing is disabled.

Both APs run at 1 Gb/s; port 6 is pinned to 1 Gb/s because 2.5 Gb/s drops the
link. The Omada reconciler keeps the switch's physical speed/duplex settings.
AP automatic firmware updates are enabled.

`deployments/homelab/network/unifi-network.yaml` records the native enrollment
settings and secret references; it is a documented desired-state input, not an
automatic UniFi API reconciler. PSKs are in `secrets/omada.yaml` under `wireless.psks`.

Radio widths are 20 MHz on 2.4 GHz, 80 MHz on 5 GHz and 160 MHz on 6 GHz.
MLO does not guarantee simultaneous data transfer over both bands, and all
upstream traffic shares the 1 Gb/s link.
Clients must support WPA3 to join Rooftrollen. Older devices use the separate
IoT WLAN and its VLAN policy.

The U7 Pro Max's dedicated `wifi3`/`scan0` radio and `ubnt-airview` daemon are
active. In Network, open **AirView > WiFi Scanner**, select the AP, and choose
**Spectrum Analyzer**. That checkbox selects a display mode; it is not a
persistent AP-enable switch. Automatic Channel AI optimization is a separate
feature and stays disabled. A full RF scan is not required to enable the
dedicated analyzer.

## Security and access

The Gateway allows the admin workstation `10.21.10.20/32` and administration
WireGuard `10.21.91.0/24`. Normal management uses native UniFi authentication.
Create a unique local owner credential in the password manager, enable available
MFA, and keep UniFi cloud Remote Access disabled. This service does not require
a UniFi gateway, UI cloud account, captive portal or a WAN port forward.

The initial local owner is `admin`. Its generated password, the separate AP SSH
credential and the UnPoller credential are encrypted in
`deployments/homelab/credentials/host-runtime/unifi.sops.yaml`, with only the repository administrator as
recipient. Values in `data` are base64 encoded inside SOPS encryption. Retrieve
the owner password into the password manager without copying it into chat or
committing plaintext. Console diagnostic sharing is disabled.

Open <https://unifi.fahrican.com> from the admin workstation or administration
VPN and sign in with the **local** `admin` account. On the Wayland workstation,
copy the password directly from SOPS to the clipboard with this command from
the repository root, then paste it into the login form or password manager:

```sh
nix run .#sops --accept-flake-config -- decrypt \
  --extract '["data"]["UNIFI_OWNER_PASSWORD"]' --output-type binary \
  deployments/homelab/credentials/host-runtime/unifi.sops.yaml \
  | base64 --decode | wl-copy
```

The access policy rejects ordinary Wi-Fi clients; use the
administration VPN when logging in from a phone.

The origin uses TLS with a VM-local private CA, a 90-day leaf certificate and
daily renewal checks. Only its public CA enters Git. Envoy validates that CA and
the `unifi-origin.internal` SAN. A host nginx proxy forwards to native UniFi OS
on loopback `11443`; certificate verification is disabled only for that loopback
hop. The guest's nftables input policy admits origin TLS and metrics (8443,
9100, 9130) only from the pod network `10.100.0.0/16` and the server subnet
`10.21.20.0/24`; native setup on `11443` and SSH only from the workstation and
VPN; and AP inform/STUN only from `10.21.90.6` and `10.21.90.7`. These sources
must still authenticate to UniFi.

SSH and the native `11443` UI provide private recovery access without the
Gateway. The WireGuard route for `10.21.40.0/24` includes the VM. RouterOS
rules permit those recovery ports and AP SSH at `.6` and `.7`; the Omada HTTPS
VPN rule allows only the switch at `.5`. No UDP discovery broadcast is routed:
adopt over layer 3.

## Bootstrap and adoption

1. Keep the `unifi` Flux stage held and restore `disk.img` into `unifi-root`
   from backup. Verify the transfer before VM startup. After starting the
   guest, inspect `cloud-init status --wait` and `systemctl status uosserver nginx`.
2. Verify the VM SSH fingerprint through the PiKVM/KubeVirt console against the
   trusted host-key record before SSH enrollment. A fresh install enrolls its
   new key separately.
3. Run `python3 components/homelab/services/unifi/enroll-origin-ca.py` in the
   repository shell. Commit its public `origin-ca.yaml` and Kustomization change.
   The Gateway fails closed until that CA is enrolled. Verify
   both HTTPRoute and BackendTLSPolicy conditions and the public certificate SAN.
4. Reconcile the scoped router entries with `--tags private-access`. Use
   `--tags static-leases` for a verified AP reservation. An extra-vars file may
   select only the corresponding inventory rows, keeping the normal preflight.
5. Open the private UI and complete local-owner setup immediately. Set the
   country to Turkey; disable remote access and wireless meshing. Keep the
   default stable automatic update policy. Create **Third-party Gateway** networks for VLANs 10 and 50;
   never create a DHCP server or gateway in UniFi.
6. Use the routed address `10.21.40.127` for adoption. Over the verified
   AP SSH connection, run
   `set-inform http://10.21.40.127:8080/inform` (or the firmware's
   `mca-cli-op set-inform ...`). Adopt only MAC `74:F9:2C:3C:99:F7`; repeat inform
   after accepting if required. Verify Connected state and the final inform URL.
   The installed UniFi OS version does not expose the older standalone
   application's Inform Host Override setting; do not write unsupported API
   fields to emulate it.
7. Apply the SSIDs from `deployments/homelab/network/unifi-network.yaml`, reusing the SOPS PSKs without
   displaying them in terminal output or passing them on a command line. Rotate
   the AP's factory SSH credential through UniFi Device SSH Settings and store
   the new credential securely. Turn on scheduled native Network backups too.
   In Network 10.5, verify each WLAN's `networkconf_id` references the intended
   third-party network; legacy WLAN `vlan` fields can be ignored by the API.
8. Join both SSIDs with real clients. Trusted clients must receive VLAN-10
   addresses; IoT clients must receive VLAN-50 addresses and keep Home
   Assistant discovery/control. Confirm IoT cannot reach management or the
   controller UI, and prove VPN access from outside the LAN. Verify 6-GHz and
   MLO association with capable clients, using Turkey's regulatory domain and
   WPA3/required PMF; do not change the country to unlock frequencies.

## Monitoring and backups

The Prometheus/Alertmanager stack scrapes node exporter and UnPoller
and sends failures through the infrastructure Telegram route. Alerts cover
controller health, origin reachability, AP disconnections, missing AP metrics,
TLS renewal and backups older than 36 hours. Host journals and sanitized Envoy
access logs support diagnosis. UnPoller keeps radio/client counters with PII
hashing and DPI collection disabled; the controller and its backups still hold
sensitive WLAN state.

Create a **local Limited Admin with Network Read Only** for UnPoller. Enroll
`UNIFI_POLLER_USERNAME` and `UNIFI_POLLER_PASSWORD` using the standard
`enroll-services-credential` workflow; use a random 24+ character password
containing letters, digits and `_+=/@.-`. Then run:

```sh
nix run .#enroll-service-host-secrets -- ubuntu@10.21.40.127 unifi-poller
nix run .#reconcile-services-backblaze -- apply --bootstrap-directory /secure/intake
nix run .#initialize-services-restic -- apply
nix run .#enroll-service-host-secrets -- ubuntu@10.21.40.127 unifi-backup
```

`UNIFI_BACKUP_RESTIC_PASSWORD` is generated in the declared SOPS file. Reuse it
for enrollment and do not regenerate it: password rotation needs a Restic key
change and a restore check.

The Backblaze reconciler consumes the usual one-time master-key intake and
creates a separate writer restricted to `services/hosts/unifi/`. Never reuse a
Velero or another host's writer. Keep the encrypted Restic password and B2
credentials recoverable offline. The guest is backed up with Restic (below).

At 02:00 UTC plus up to 30 minutes, `unifi-backup` verifies repository access,
stops UniFi and its updater, verifies its Podman container is stopped, stages
an archive with numeric IDs/xattrs, restarts management and only then uploads
with Restic. Errors while staging trigger a restart. AP forwarding continues.
Retention is 14 daily, 8 weekly, 12 monthly and 3 yearly snapshots. The exported
success timestamp advances only after upload and retention succeed. A missing
credential or failed backup generates a stale-backup alert rather than a false
success. Allow space for the live state and two archive generations.

Run an initial `sudo systemctl start unifi-backup.service` and inspect
`journalctl -u unifi-backup.service`. A successful job alone is insufficient:
complete the isolated restore below.

## Restore and upgrades

1. Create an isolated recovery VM in its own namespace using the same pinned
   Ubuntu image and UniFi installer, with a deny-all NetworkPolicy except
   operator SSH/UI and the temporary offsite restore connection, and no VLAN-90
   or VLAN-40 NIC. Complete blank installation before loading the saved
   identity. The restored controller must have **no path to VLAN 90,
   production APs, the production inform address or UniFi cloud remote access**.
2. Deliver the restore credential and Restic password privately. Restore a
   selected `unifi` snapshot into a mode-0700 staging directory, use
   `restic check --read-data`, and verify `controller.tar` can be read completely.
3. Stop `uosserver` and `uosserver-updater`. Inspect the archive's recorded
   `etc/passwd`, `etc/group`, `etc/subuid` and `etc/subgid`; require the fresh
   `uosserver` UID/GID and subordinate ID mappings to match. Do not overwrite
   the recovery host's whole account database.
4. Extract `home/uosserver`, `var/lib/uosserver`, `var/lib/unifi-proxy` and the
   declared UniFi service units with numeric owners/xattrs preserved. Restore
   scripts/proxy configuration when recovering the full host. Keep recovery
   SSH keys and networking separate. Reboot the recovery VM while keeping
   network isolation so Podman recreates its volatile runtime directories for
   the restored container. Restarting only `uosserver` after replacing a blank
   installation's persistent state can fail with `cannot chown run directory`.
   Verify controller startup, then log in through the restricted recovery UI.
5. Verify the site, AP MAC, both VLAN mappings, SSIDs, owner account and native
   backup settings. APs should appear disconnected in isolation. Record the
   snapshot ID, versions and the restore result; then shut down the recovery
   controller before lifting any isolation.
6. For actual failover, stop/fence the old controller first. Restore its CA or
   re-enroll the replacement public CA, assign `10.21.40.127`, and
   verify AP reconnection before enabling scheduled jobs. Never run two restored
   controller identities against the live AP.

Keep offsite backups verified before the automatic update window (the native
OS default is weekly, Sunday at 00:00). AP automatic updates are enabled.
The installer pin records the initial release; native updates may advance the
running version. For a manually promoted bootstrap release, update the installer
URL/hash after reviewing its official release, then run that installer on the
running VM over pinned SSH; replacing cloud-init does not rerun it. For script
updates, deliver the checked-in `components/homelab/services/unifi` files to
`/usr/local/lib/unifi` as root and rerun `bootstrap.sh`. A schema upgrade can make
an old binary incompatible with the new database: rollback means restoring the
matching pre-upgrade data and binary in isolation, not just installing an older
version. Promote AP firmware separately after client tests. Rotate the private
origin CA with overlapping trust before its ten-year expiry.

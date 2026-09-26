# UniFi access points

UniFi owns only the APs and WLAN configuration. The CCR2004 keeps routing,
DHCP, DNS, firewall policy and WireGuard; the CRS and existing Omada switch keep
switching. Future MikroTik switches must preserve the same VLAN trunk contract.
Omada remains in service until its last switch is replaced. Its reconciler now
uses `scope: switch-only`, so an offline EAP cannot block switch maintenance.

See [migration validation](migration-validation.md) for the dated deployment,
AP connectivity and backup results. The address and monitoring definitions below
describe the intended deployment; that record identifies checks still pending.

The native UniFi OS Server runs on a dedicated Ubuntu 24.04 OpenStack VM:
2 vCPU, 4 GiB RAM, 2 GiB swap and a retained 64 GiB Cinder boot volume. Both
VM and volume have `prevent_destroy`. A controller outage leaves adopted APs
forwarding their last configuration, but prevents management and telemetry.
Ubiquiti recommends [UniFi OS Server](https://help.ui.com/hc/en-us/articles/34210126298775-Self-Hosting-UniFi)
for new self-hosted installations; it requires host services and is not packaged
as an official standalone Kubernetes container.

## Addresses and ownership

| Purpose | Address or configuration |
| --- | --- |
| Private browser access | `https://unifi.fahrican.com` through Envoy `10.21.40.122` |
| Controller VM | `192.168.80.12`, routed floating address `10.21.40.127` |
| AP inform endpoint | `http://10.21.40.127:8080/inform` |
| AP STUN | `10.21.40.127:3478/udp` |
| U7 Pro Max | `74:F9:2C:3C:99:F7`, DHCP reservation `10.21.90.6` |
| Physical attachment | SG3210XHP-M2 port 6, `infra-ap-trunk` |
| Temporary Ethernet limit | Port 6 at 1 Gb/s full duplex; 2.5 Gb/s fails reachability on the current cable/switch path, including after AP firmware 8.7.11 |
| AP management | Untagged at the AP, switch PVID/native VLAN 90 |
| Trusted WLAN | `Rooftrollen`, tagged VLAN 10 |
| IoT WLAN | `Rooftrollen_IoT`, tagged VLAN 50 |

The router's management DHCP service is **static-only**. A replacement AP needs
its own verified Ethernet MAC reservation before it can receive an address.
Do not copy the EAP MAC or enable a general DHCP pool. The unplugged EAP retains
its old static `10.21.90.4` for rollback. Do not set a VLAN 90 management override
on the U7: its management traffic is untagged on this switch port.

The switch's physical speed/duplex settings are preserved by the Omada
reconciler. Keep the recorded 1 Gb/s workaround until a cable/port/firmware test
can sustain 2.5 Gb/s. Test a known-good short cable on the same port first; the
current evidence does not distinguish cable, AP PHY and switch interoperability.

`../../unifi-network.yaml` records the native enrollment settings and secret
references; it is a documented desired-state input, not an automatic UniFi API
reconciler. Wi-Fi names and PSKs survive the migration. The PSKs remain in the
existing SOPS `secrets/omada.yaml` document during the switch transition.

## Security and access

The Gateway allows the admin workstation `10.21.10.20/32` and administration
WireGuard `10.21.91.0/24`. Normal management uses native UniFi authentication.
Create a unique local owner credential in the password manager, enable available
MFA, and keep UniFi cloud Remote Access disabled. This service does not require
a UniFi gateway, UI cloud account, captive portal or a WAN port forward.

The initial local owner is `admin`. Its generated password, the separate AP SSH
credential and the UnPoller credential are encrypted in
`../../host-runtime/unifi.sops.yaml`, with only the repository administrator as
recipient. Values in `data` are base64 encoded inside SOPS encryption. Retrieve
the owner password into the password manager without copying it into chat or
committing plaintext. Console diagnostic sharing is disabled.

The origin uses TLS with a VM-local private CA, a 90-day leaf certificate and
daily renewal checks. Only its public CA enters Git. Envoy validates that CA and
the `unifi-origin.internal` SAN. A host nginx proxy forwards to native UniFi OS
on loopback `11443`; certificate verification is disabled only for that loopback
hop. Neutron admits origin TLS and metrics only from the private services
subnet; native setup on `11443` and SSH are limited to the workstation and VPN.
These private services-network sources are trusted for origin access and must
still authenticate to UniFi. AP inform/STUN ingress is limited to `10.21.90.6/32`.

SSH and the native `11443` UI provide private recovery access independent of
Kubernetes. The existing WireGuard route for `10.21.40.0/24` already includes
the VM. Declared RouterOS rules permit those specific recovery ports and AP
SSH at `.6`; the Omada HTTPS VPN rule now targets only the switch at `.5`.
No UDP discovery broadcast is routed: use explicit layer-3 adoption.

## Bootstrap and adoption

1. Reconcile `wave85-unifi`. It provisions only the dedicated UniFi resources
   using the existing services network/flavor and pinned Ubuntu Glance image.
   Cloud-init installs the official checksum-pinned installer in
   `components/cloud/services/unifi/inputs.json`, nginx, node exporter and the
   backup/renewal timers. Cloud-init contains no passwords or private keys.
2. Verify the VM SSH fingerprint through the OpenStack console. Add its public
   key to `deployments/homelab/ssh-host-keys.json` and the operator's trusted
   known-hosts set before SSH enrollment. Inspect `cloud-init status --wait`
   and `systemctl status uosserver nginx` through this verified connection.
3. Run `python3 components/cloud/services/unifi/enroll-origin-ca.py` in the
   repository shell. Commit its public `origin-ca.yaml` and Kustomization change.
   The Gateway intentionally fails closed until that CA is enrolled. Verify
   both HTTPRoute and BackendTLSPolicy conditions and the public certificate SAN.
4. Reconcile the scoped router entries with `--tags private-access`. Use
   `--tags static-leases` for a verified AP reservation. An extra-vars file may
   select only the corresponding inventory rows, keeping the normal preflight.
5. Open the private UI and complete local-owner setup immediately. Set the
   country to Turkey; disable remote access and wireless meshing. Retain the
   default stable automatic update policy. Create **Third-party Gateway** networks for VLANs 10 and 50;
   never create a DHCP server or gateway in UniFi.
6. Use the routed address `10.21.40.127` for explicit adoption. Over the verified
   AP SSH connection, run
   `set-inform http://10.21.40.127:8080/inform` (or the firmware's
   `mca-cli-op set-inform ...`). Adopt only MAC `74:F9:2C:3C:99:F7`; repeat inform
   after accepting if required. Verify Connected state and the final inform URL.
   The installed UniFi OS version does not expose the older standalone
   application's Inform Host Override setting; do not write unsupported API
   fields to emulate it.
7. Apply the SSIDs from `../../unifi-network.yaml`, reusing the SOPS PSKs without
   displaying them in terminal output or passing them on a command line. Rotate
   the AP's factory SSH credential through UniFi Device SSH Settings and store
   the new credential securely. Turn on scheduled native Network backups too.
   In Network 10.5, verify each WLAN's `networkconf_id` references the intended
   third-party network; legacy WLAN `vlan` fields can be ignored by the API.
8. Join both SSIDs with real clients. Trusted clients must receive VLAN-10
   addresses; IoT clients must receive VLAN-50 addresses and retain Home
   Assistant discovery/control. Confirm IoT cannot reach management or the
   controller UI, and prove VPN access from outside the LAN. Qualify 6 GHz
   afterward using the real Turkey regulatory domain and WPA3/PMF requirements;
   do not change the country to unlock frequencies.

## Monitoring and backups

The existing Prometheus/Alertmanager stack scrapes node exporter and UnPoller
and sends failures through the infrastructure Telegram route. Alerts cover
controller health, origin reachability, AP disconnections, missing AP metrics,
TLS renewal and backups older than 36 hours. Host journals and sanitized Envoy
access logs support diagnosis. UnPoller retains radio/client counters with PII
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

`UNIFI_BACKUP_RESTIC_PASSWORD` is already generated in the declared SOPS file
and protects the local migration checkpoint. Reuse it for enrollment. Do not
regenerate it while repositories still require the existing password; password
rotation needs an explicit Restic key migration and recovery verification.

The Backblaze reconciler consumes the usual one-time master-key intake and
creates a separate writer restricted to `services/hosts/unifi/`. Never reuse a
Velero or another host's writer. Keep the encrypted Restic password and B2
credentials recoverable offline. The controller VM is backed up with Restic;
Velero does not back up its Cinder volume.

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
complete the isolated restore below before treating the migration as recovered.

## Restore and upgrades

1. Create an isolated recovery VM using the same pinned Ubuntu image and UniFi
   installer. Its security group must allow only operator SSH/UI and the
   temporary offsite restore connection. It must have **no path to VLAN 90,
   production APs, production inform address or UniFi cloud remote access**.
   Never attach the production floating IP to a test clone.
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
   SSH keys and networking independent. Start the controller while still
   isolated, and log in through the restricted recovery UI.
5. Verify the site, AP MAC, both VLAN mappings, SSIDs, owner account and native
   backup settings. APs should appear disconnected in isolation. Record the
   snapshot ID, versions and the restore result; then shut down the recovery
   controller before lifting any isolation.
6. For actual failover, stop/fence the old controller first. Restore its CA or
   explicitly re-enroll the replacement public CA, assign `10.21.40.127`, and
   verify AP reconnection before enabling scheduled jobs. Never run two restored
   controller identities against the live AP.

Keep offsite backups verified before the automatic update window (the native
OS default is weekly, Sunday at 00:00). AP automatic updates remain enabled.
The installer pin records the initial release; native updates may advance the
running version. For a manually promoted bootstrap release, update the installer
URL/hash after reviewing its official release, then run that installer on the
existing VM over pinned SSH; replacing cloud-init does not rerun it. For script
updates, deliver the checked-in `components/cloud/services/unifi` files to
`/usr/local/lib/unifi` as root and rerun `bootstrap.sh`. A schema upgrade can make
an old binary incompatible with the new database: rollback means restoring the
matching pre-upgrade data and binary in isolation, not just installing an older
version. Promote AP firmware separately after client tests. Rotate the private
origin CA with overlapping trust before its ten-year expiry.

For immediate wireless rollback, unplug the U7 and reconnect the EAP on port 6.
The port profile, old AP address and Omada WLAN objects have been preserved.

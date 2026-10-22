# UniFi access points

UniFi owns only the APs and WLAN configuration. The CCR2004 keeps routing,
DHCP, DNS, firewall policy and WireGuard; the CRS and Omada switch keep
switching (Omada's reconciler uses `scope: switch-only`, so an offline AP never
blocks switch maintenance). A controller outage leaves adopted APs forwarding
their last configuration; only management and telemetry stop.

UniFi OS Server is not packaged as a Kubernetes container, so it runs natively
in one Ubuntu 24.04 KubeVirt guest (`vm.yaml`). Its disk lives in the
`unifi-root` claim, which Velero does not copy; the guest backs itself up with
Restic. The guest has a masquerade NIC and a bridged services-LAN NIC with the
fixed address used for AP inform, STUN and the gateway backend.

## Guest configuration

`components/homelab/services/unifi` is the only copy of the guest scripts,
installer pin and nftables ruleset. Kustomize turns them into the `unifi-guest`
ConfigMap, which KubeVirt attaches as a read-only disk; cloud-init's `bootcmd`
installs it into `/usr/local/lib/unifi` and `/etc/nftables.conf` on **every
boot**. Restart the VM to apply script or firewall changes. `bootstrap.sh`
(installer, nginx, timers, UnPoller unit) runs only on first boot; rerun it
over SSH after changing what it writes. The installer pin records the initial
release; UniFi's own updater advances the running version afterwards.

## Network invariants

- Router management DHCP is **static-only**: a replacement AP needs a verified
  MAC reservation first. Never enable a pool or a VLAN 90 management override
  (AP management is untagged on its port). Option 43 points new APs at the
  inform address; layer-2 discovery is not routed.
- UniFi WLANs use **Third-party Gateway** networks; never create a DHCP server
  or gateway in UniFi. Verify each WLAN's `networkconf_id`; the API ignores
  legacy `vlan` fields.
- The WLAN settings are recorded in [network](../../../../../docs/network.md#wireless);
  they are not reconciled automatically. PSKs are in
  `secrets/omada.yaml`. Keep the country set to Turkey; never change it to
  unlock channels.
- Port 6 on the SG3210XHP is pinned to 1 Gb/s; 2.5 Gb/s drops the link.

## Access

The private gateway's SecurityPolicy admits only the admin workstation and the
administration WireGuard network; sign in with the **local** owner (credentials
in `deployments/homelab/credentials/host-runtime/unifi.sops.yaml`). UniFi cloud
remote access stays disabled.

Envoy verifies the origin's TLS against the public CA in `origin-ca.yaml` and
the `unifi-origin.internal` SAN. The CA key never leaves the guest; nginx
forwards to UniFi on loopback 11443, the only hop without verification. The
guest firewall can only distinguish the whole pod network, so the
`unifi-origin-clients` Cilium policy denies the origin and exporter ports to
every pod outside the gateway and monitoring namespaces. SSH and native 11443
remain reachable from the workstation and VPN for recovery without Kubernetes.

A fresh guest generates a new origin CA: verify its SSH host key on the
console, then run `python3 components/homelab/services/unifi/enroll-origin-ca.py`
and commit `origin-ca.yaml`. The route fails closed until then.

## Monitoring

Prometheus scrapes node exporter (health and backup textfile metrics) and a
local UnPoller using a **Limited Admin, Network Read Only** account with PII
hashing and DPI disabled. Alerts cover controller health, origin reachability,
AP disconnects, missing AP telemetry, TLS renewal and backups older than 36
hours. Deliver the poller and backup credentials with
`enroll-service-host-secrets ubuntu@<vm> unifi-poller|unifi-backup`.

## Backups

`unifi-backup` stops UniFi so its Podman databases are consistent, archives the
controller state, proxy TLS and service units to `controller.tar` with numeric
owners and xattrs, restarts UniFi, and only then uploads with Restic to its own
B2 prefix (`services/hosts/unifi/`, a writer used by nothing else). The success
metric advances only after upload and retention. Never regenerate
`UNIFI_BACKUP_RESTIC_PASSWORD`: rotation needs a Restic key change and a
restore test.

## Restore

The backup is a Restic snapshot of `controller.tar`, not a disk image.

1. Keep the `unifi` Flux stage held. Build the guest fresh (an empty
   `unifi-root`, or an isolated test VM in its own namespace with no services-LAN
   or VLAN 90 path) and let `bootstrap.sh` install the pinned UniFi OS.
2. Restore the snapshot into a mode-0700 directory, run
   `restic check --read-data`, and read `controller.tar` completely.
3. Stop `uosserver` and `uosserver-updater`. Require the archive's
   `uosserver` UID/GID and subuid/subgid ranges to match the fresh install; do
   not overwrite the whole account database.
4. Extract `home/uosserver`, `var/lib/uosserver` and `var/lib/unifi-proxy` with
   numeric owners and xattrs, then **reboot** so Podman recreates its runtime
   directories (restarting only `uosserver` fails with `cannot chown run
   directory`).
5. Verify the site, AP MACs, VLAN mappings, SSIDs and owner. In isolation the
   APs appear disconnected; shut the test controller down before lifting
   isolation. For real failover, fence the old controller first and never run
   two controller identities against live APs. Restoring `var/lib/unifi-proxy`
   keeps the enrolled origin CA; otherwise re-enroll it.

A UniFi schema upgrade can make older binaries incompatible: rollback means
restoring matching pre-upgrade data and binary in isolation. Keep a verified
off-site backup before UniFi's weekly automatic update window.

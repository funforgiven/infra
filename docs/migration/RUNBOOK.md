# NixOS and Kubernetes migration execution

This runbook is for a separately authorized future outage. Preparation has not
applied any target configuration, changed a running server or copied final app
data. Use the prepared branch `codex/nixos-kubernetes-migration`; keep the main
checkout and source revision `8d5f130` available for recovery. Downtime is
acceptable, so use a deliberate stop/export/reinstall/restore sequence.

## 1. Review and qualify before the outage

Read [ARCHITECTURE.md](ARCHITECTURE.md), [INVENTORY.md](INVENTORY.md),
[DATA-MIGRATION.md](DATA-MIGRATION.md), [DECISIONS-REQUIRED.md](DECISIONS-REQUIRED.md)
and [CONSOLE-ACCESS.md](CONSOLE-ACCESS.md). Obtain the off-server staging location,
PiKVM access/port mapping, physical reset availability and maintenance start
time. Software choices do not need to be reopened to execute the plan.

Freeze a reviewed commit and record its hash, flake lock, schema/chart hashes,
inventory capture time and validation results. Publish that signed commit to
the reviewed Git branch only as an execution prerequisite; the preparation
task does not publish or deploy it. Flux verifies the source HEAD using the
existing trusted SSH signing key. Update `gotk-sync.yaml` if a different final
branch is selected; do not bootstrap from an unpublished or unsigned HEAD.

Repeat the offline acceptance commands from [VALIDATION.md](VALIDATION.md): all
host/disks evaluate, the combined homelab check builds, all provider configs
validate, and every pinned Helm/native manifest passes full schema validation.
Keep recovery copies of the operator age identity and private signing/access
key independent of the desktop and cluster. Ensure pinned runtime/container
images and the Matrix image can be recovered without a running Forgejo registry;
export needed images or cache them on the workstation before its outage.

Test PiKVM's HDMI/USB, keyboard layout, host identity and virtual-media boot on
each motherboard. Keep its power and access independent of the retiring cluster.
No ATX means the owner handles powered-off/frozen hosts. Record an official
NixOS installer ISO URL/version/SHA-256 and verify the actual downloaded bytes;
mount that reviewed image through PiKVM. The installer and target system are
separate artifacts: the target comes from the locked migration flake.

Run a representative cold export/test restore, native PostgreSQL recovery,
UniFi offline preparation and transfer-image qualification before scheduling.
Check capacity with measured bytes, not requested claim sizes. The inventory's
unidentified cloud devices and ephemeral Nova roots must have backend identities
and independent archives before any destructive step.

## 2. Stop writers and finish independent recovery packages

Use the explicit source wrappers in DATA-MIGRATION. Suspend old Flux/Helm and
cloud provisioning/provider reconcilers, app CronJobs and runners; record their
original states. Stop ingress and all external/application writers. Complete
final native DB backups/WAL and their isolated restore checks, then stop each
app and cold-export its files. Cleanly shut down UniFi and source guests before
raw-device/root-image copies. Keep the source APIs needed by remaining exports running until backend
identification, transfers and verification finish. Cloud APIs may retire after
their authoritative metadata and native database backups qualify; the remaining
RBD exports still require source Ceph and the physical Kubernetes API.

Run `migration-source-capture` into a fresh independent private directory as
documented in DATA-MIGRATION; check its complete manifest and review changes.
Refresh the private runtime/OIDC/provider/certificate snapshots immediately
before execution. The prepared snapshots have capture timestamps and are not
live backups. Compare four retained provider state lineages/serials against the
final source archive and export them into private local files. Source cloud-only
states remain encrypted in the rollback package. Do not discard them by removing
the old operator/controller.

The installer boot gate requires checked, independently readable exports for
every required claim and guest/image disposition, successful isolated native/app
restores, independent administration keys and a verified rollback package. All
source-dependent export jobs must finish before pecorino leaves Ubuntu. This
gate permits booting the installer to archive stopped source filesystems.

The SATA formatting gate additionally requires that selected host's cold root,
boot and both EFI partitions to have verified Backblaze/native recovery proofs,
with partition/RAID/LVM metadata preserved, and its actual installer disk
identities matched to the reviewed disko selection. Seal those proofs before
formatting. Record both gates explicitly in the private execution ledger.

## 3. Release old address ownership and retire source writers

Stop source VM/control planes and all old API/cloud/LB ownership of addresses
that will be reclaimed. Live inspection identified the API owner as kube-vip
static Pods on all three Ubuntu hosts, using
`/etc/kubernetes/manifests/kube-vip.yml`; no source keepalived service is present.
These Pods also advertise source services. After the completed export gate,
verify each captured manifest hash and preserve it outside the kubelet static
manifest directory to hold its controller. Verify the processes have exited and
`.20.128` is absent on all old hosts before target keepalived advertises it.

Independent SSH/sudo and original-CA/client-certificate-validated API access at
`.20.10–12:6443` are qualified without the VIP. Use a surviving old host directly
for any remaining source administration after pecorino boots the installer; the
frozen convenience wrapper depends on pecorino and `.20.128`. Neutron/OVN/Octavia can still answer ARP
after application Pods stop: verify the actual owner and stop it. Keep the
physical management/Ceph VLAN addressing and workstation administration path
available. Verify no old owner remains before advertising each target VIP.

Retained target addresses are physical `.20.10–12/.30.10–12`, API `.20.128`, DNS
`.20.129`, management HTTPS `.20.131`, HA LAN `.40.120`, services/Forge `.40.122`,
Factorio `.40.123`, Valheim `.40.124`, UniFi `.40.127`, public Matrix `.40.128` and
NetBird STUN `.40.129`. IoT identities remain `.50.10/.50.11` and the two
radio endpoints `.50.20/.50.21`. AWS mail EIP/DNS and its public mail listeners
stay outside the local cutover. Retired guest/OpenStack/native-runner addresses
are explicitly listed in the inventory. Read-only Neutron/Octavia inspection
identifies `.40.197` as the actual Magnum workload Kubernetes API; archive its
control plane and replace it with the physical `.20.128` API. `.40.121` was an
obsolete desired/reserved guest API endpoint. Reject any newly observed address
without an explicit ownership disposition; never infer deletion from port DOWN.

DNS names and app certificates retain their identities. Rebuilt Kubernetes
uses its new API CA; old kubeconfigs must be archived and replaced. SSH Ed25519
host keys are preserved. Refresh trusted workstation known-hosts only against
the recorded identity, not by disabling host verification.

## 4. Install the three NixOS hosts, one at a time

Boot the reviewed installer on pecorino first. Set up temporary installer
networking on the existing tagged management VLAN/LACP fabric; verify both
physical NICs, link/FEC, host identity and a reachable SSH address. Install the
operator public key from `secrets/github-ssh-key.pub` into the live installer's
root authorized keys using the console. Disable installer password SSH after
key access works. Record its temporary SSH host fingerprint separately from
the preserved final host identity. Keep PiKVM on that port while virtual media
is needed.

Inspect live `lsblk -b -o NAME,PATH,SIZE,MODEL,SERIAL,WWN,TYPE`, `readlink -f` for
each inventoried by-path connector, `wipefs -n` and `mdadm --examine`. Match
`live-hardware-inventory.json` and `deployments/homelab/hosts/inventory.json`.
Only the two SATA members appear in disko; neither NVMe device is a disko
target. Stop on any connector/serial/size mismatch. Evaluate the selected
host's disko devices again from the reviewed flake before formatting.

Before formatting, archive the now-stopped Ubuntu filesystems. Mark only the
inventoried SATA devices and source filesystem block devices read-only; assemble
existing RAID/LVM read-only without mounting source filesystems. Match the four
captured filesystem UUIDs, types and sizes: root LV, boot RAID filesystem and
both EFI partitions. Export each complete filesystem, preserve its partition
and RAID/LVM identities, and store it encrypted in Backblaze. Download the exact
versions, authenticate/decompress them into private standalone disk copies and
check native QCOW2 integrity, all virtual bytes and filesystem readability.
For the root, verify the preserved SSH host key, Kubernetes PKI/Rook paths and a
native restoration of its cold etcd database. Seal the selected host's four
proofs in the verified execution package. The original six Ceph NVMes remain
outside both this archive operation and disko.


Prepare an owner-only `extra-files` directory outside Git, containing:

| Destination | Encrypted source | Mode |
| --- | --- | --- |
| `/var/lib/sops-nix/key.txt` | `secrets/kubernetes.yaml`, `cluster.host_age_identity` | 0600; parents 0700 |
| `/etc/ssh/ssh_host_ed25519_key` | `deployments/homelab/hosts/secrets.sops.yaml`, `hosts.<hostname>.ssh_host_ed25519_key` | 0600 |

Decrypt only those fields directly into their files through SOPS/Python memory,
with umask 077 and no value-bearing output. Do not copy the operator or Flux age
private key onto the physical hosts. Verify the public host-key fingerprint
from the extracted key against the captured source before installation. The
target sops-nix module installs the same host key and K3s/console/backup secrets.

For pecorino, the private files can be prepared without printing values:

```sh
export PRIVATE_EXTRA_FILES="$PRIVATE_EXECUTION_DIR/pecorino-extra-files"
install -d -m 0700 "$PRIVATE_EXTRA_FILES/var/lib/sops-nix" "$PRIVATE_EXTRA_FILES/etc/ssh"
sops decrypt --extract '["cluster"]["host_age_identity"]' secrets/kubernetes.yaml \
  > "$PRIVATE_EXTRA_FILES/var/lib/sops-nix/key.txt"
sops decrypt --extract '["hosts"]["pecorino"]["ssh_host_ed25519_key"]' deployments/homelab/hosts/secrets.sops.yaml \
  > "$PRIVATE_EXTRA_FILES/etc/ssh/ssh_host_ed25519_key"
chmod 0600 "$PRIVATE_EXTRA_FILES/var/lib/sops-nix/key.txt" "$PRIVATE_EXTRA_FILES/etc/ssh/ssh_host_ed25519_key"
ssh-keygen -y -f "$PRIVATE_EXTRA_FILES/etc/ssh/ssh_host_ed25519_key" | ssh-keygen -lf -
```

Use the matching host field and private directory for each subsequent server.
After the recorded SATA gate, the future installation command is:

```sh
nix run --inputs-from . nixos-anywhere -- \
  --flake .#pecorino --target-host root@INSTALLER_ADDRESS \
  --extra-files "$PRIVATE_EXTRA_FILES"
```

Use the locked nixos-anywhere input and the reviewed flake. This command runs
disko and destroys the selected SATA contents. Do not use `--copy-host-keys`
from the installer: those would be temporary installer keys. The [upstream
extra-files mechanism](https://nix-community.github.io/nixos-anywhere/howtos/secrets.html)
delivers the prepared keys before target activation. Record actual commands,
exit codes and host/disk identities. Remove plaintext temporary files when the
verified installation no longer needs them.

Boot pecorino and verify SSH fingerprint, SOPS, root console login, both MD
members, EFI boot path, NIC LACP/RS-FEC, management MTU 1500 and Ceph MTU 9000.
Inspect `systemctl status k3s keepalived`, the local API `/readyz` and expected
`.20.128` ownership. Cilium is not installed yet, so Node Ready/pod scheduling
is a later check. Copy the new owner-only admin kubeconfig, replace its server
with `https://10.21.20.128:6443`, and use it explicitly for target operations.

Install taleggio and asiago with their own host names/extra-files and the same
disk identity checks. They join embedded etcd through the API VIP using the
prepared K3s token. Verify all three server/etcd members and the physical labels.
Test boot with either SATA member unavailable one host at a time, respecting
quorum; never remove two etcd/Ceph failure domains simultaneously. Physically
disconnecting a disk is owner work. Repair/resync any degraded mirror before
proceeding.

## 5. Bootstrap CNI, then the recovery Flux graph

Flux Pods cannot bootstrap a missing CNI. Install the pinned Cilium release
using the same values file as the Flux HelmRelease. Run Helm from the workstation
against the enrolled target kubeconfig. These commands change the target only:

```sh
target apply -f deployments/homelab/cluster/infrastructure/cilium/vendor/
target wait crd/ciliumnetworkpolicies.cilium.io --for=condition=Established --timeout=2m
helm pull oci://quay.io/cilium/charts/cilium --version 1.20.2 --destination /tmp
echo 'b2afd87b7f75f875f92a14559f14f59b7babbb479d968e3fd625a20bf30ec20e  /tmp/cilium-1.20.2.tgz' | sha256sum --check
helm upgrade --install cilium /tmp/cilium-1.20.2.tgz --namespace kube-system \
  --values deployments/homelab/cluster/infrastructure/cilium/values.yaml --wait --timeout 20m
target rollout status daemonset/cilium -n kube-system --timeout=20m
target rollout status deployment/cilium-operator -n kube-system --timeout=20m
target wait nodes --all --for=condition=Ready --timeout=20m
target -n kube-system exec daemonset/cilium -- cilium-dbg status --verbose
```

Require kube-proxy replacement to be active on every node, with no kube-proxy
process or DaemonSet. Verify pod DNS, cross-host traffic, IPv4 masquerading,
allowed/denied application flows and Cilium health before proceeding. Keep
MetalLB and Envoy Gateway for the retained Local traffic policies. Verify client
addresses and VIP failover after these controllers start. Check `/opt/cni/bin`
and `/etc/cni/net.d`: K3s flannel is disabled, the static secondary plugins are
installed by NixOS, and `cni.exclusive: false` preserves Multus. Qualify HA/OTBR
multicast and UniFi's secondary VLAN independently of the primary CNI.

Flux later adopts the existing Helm release with the identical values and chart
manifest digest `sha256:a7c12d330dd96bfcda3bf057b24be8f36566c34868265f930f776dff6f42d838`.

Create the root namespaces, then seed the approved gateway certificate/account
bundle **before** installing the root graph:

```sh
target apply -f deployments/homelab/cluster/namespaces.yaml
nix run .#migration-certificate-bundle -- --output "$PRIVATE_EXECUTION_DIR/gateway-seed.yaml"
target create -f "$PRIVATE_EXECUTION_DIR/gateway-seed.yaml"
```

`create` refuses accidental overwrites. Record the seeded public certificate
fingerprints. If retrying, compare the existing fingerprints; do not overwrite
a certificate that cert-manager has renewed. Remove the private local bundle
after recovery. Keep the ACME account and Cloudflare token encrypted in the
normal credentials; cert-manager owns subsequent gateway TLS renewal.

Install Flux components. Deliver only `cluster.flux_age_identity` from the
encrypted `secrets/kubernetes.yaml` as the `flux-system/sops-age` Secret via
stdin; do not print or commit it. Bootstrap `deployments/homelab/recovery`,
which sets the initial root sync path and suspends Ceph, observability and stateful apps.
Do not apply the normal `gotk-sync.yaml` first: it would release the normal graph
before restore holds exist.

```sh
target apply -f deployments/homelab/cluster/bootstrap/flux/gotk-components.yaml
target -n flux-system wait deployment/source-controller --for=condition=Available --timeout=10m
target apply -k deployments/homelab/recovery
target -n flux-system get gitrepositories,kustomizations
```

Verify the GitRepository revision/signature and SOPS decryption. Require the
recovery root path and all restore holds before storage/app operations. Once
the recovery graph has been installed, suspend the **root** `flux-system`
Kustomization while releasing individual held stages during the outage. Without
that root suspension, it would reapply `suspend:true` on the next reconciliation.
Its GitRepository continues fetching, and child infrastructure Kustomizations
continue independently. Record each deliberate release in the execution ledger.

## 6. Initialize fresh Ceph only after the NVMe reuse gate

The NVMe reuse gate repeats full independent-data coverage, native restore
proofs and source rollback metadata verification. Formatting an old OSD ends
the simple source rollback option. Do not assume the new Rook operator can
adopt an unrelated FSID from existing device signatures.

The recovery overlay holds the `ceph` Kustomization from initial bootstrap;
keep it suspended until that gate is recorded. With all
old storage writers stopped, deliberately clear only the six inventoried NVMe
devices using the reviewed Rook/Ceph cleanup procedure. Record exact connectors,
serials and the old FSID before each destructive device command. Never run a
host-wide wildcard wipe, include SATA, or enable Rook `useAllDevices`.

Release `ceph` and require three healthy monitors, six OSDs, three host failure
domains, replica 3/minimum 2 pools, CephFS active/standby MDS and HEALTH_OK.
Release/verify `storage` and snapshot controllers. Create a disposable RBD
claim and CephFS RWX claim; write, hash, remount on another node and verify.
Verify snapshot/clone behavior and capacity before restoring app volumes.

Rook stores monitor state under `/var/lib/rook` on the SATA roots. Include it in
future recovery planning; preserving NVMe devices while losing all monitors and
keys is not a tested Ceph restore strategy.

## 7. Restore monitoring, native databases and apps

Keep each writer stage held while restoring. Precreate implicit claim names
using `migration-volume-plan`, restore monitoring files as DATA-MIGRATION
specifies, then delete transfer Pods so RWO volumes detach. Release
`observability` first and require Grafana/Loki/Prometheus/Alertmanager readiness
and working monitoring CRDs. This unlocks the database controller stage.
Restore old physical history into independent archives, and merge active
silences through the API; do not merge binary TSDB/Alertmanager directories.

Require CNPG/Barman controllers, then release `identity-database` for native
recovery. Verify the final backup ID/LSN, original masterkey/login identity and
application contents before releasing `identity`. Require preserved ZITADEL
login/roles/OIDC clients and API OIDC authentication. Break-glass admin kubeconfig
and SSH remain available while SSO is down.

Restore file claims and native SQL dumps before releasing Forge, Matrix, media,
Wallos, games or home automation. For logical databases initialize only their
database resources and restored credentials/scripts while app consumers and
schedulers remain held. Restore both Matrix databases and AudioMuse using
matching PostgreSQL versions, verify counts/ownership, then release writers.
Load needed Matrix/runtime images from the independent image archive until the
restored Forge registry is available. CNPG itself provisions replica claims.

Restore UniFi's prepared raw boot disk while its Kustomization remains held:

```sh
nix run .#migration-volume-plan -- --cloud-volume-id a7dbe35a-ddfa-41fe-ae76-13481f3bc8c6 \
  --direction restore --new-claim > "$PRIVATE_EXECUTION_DIR/unifi-transfer.yaml"
target apply -f "$PRIVATE_EXECUTION_DIR/unifi-transfer.yaml"
target -n unifi wait pod/migration-copy --for=condition=Ready --timeout=10m
target -n unifi exec -i migration-copy -- tee /data/disk.img.partial >/dev/null < "$UNIFI_PREPARED_RAW"
```

Compare workstation and in-Pod SHA-256 of the prepared copy. Only after they
match, rename to `/data/disk.img`, set `107:107` and mode 0600, and delete the
transfer Pod. Require KubeVirt/Multus readiness and no old `.127` owner before
releasing UniFi. Verify services NIC addressing/default route, origin TLS,
native UI, controller identity, adopted APs, metrics and off-server backup.

For IoT verify `iot0` tagged VLAN 50 on every host, `.50.10` HA macvlan and
`.50.11` OTBR identity, required multicast/IPv6 on the secondary attachment,
Matter port/interface selection and reachability to both radios. The primary
pod network and NixOS host have no IoT host address. Confirm restored datasets
and pairing before testing device operations; do not start parallel radio
controllers. Verify HA HTTPS and its separate `.40.120:8123` trusted-LAN route.

NetBird native database recovery must preserve account/peer identities. Release
server/operator/access stages in dependency order and verify peer connections,
routes, policies and split DNS. Complete remaining app qualification before
synthetic monitoring and schedulers resume.

Before restoring Matrix/AudioMuse logical dumps, export the exact database-only
bootstrap into private staging while their Flux stages remain held:

```sh
nix run .#migration-database-bootstrap -- matrix \
  --output "$MIGRATION_DIR/matrix-database.yaml"
nix run .#migration-database-bootstrap -- audiomuse \
  --output "$MIGRATION_DIR/audiomuse-database.yaml"
kubectl apply -f "$MIGRATION_DIR/matrix-database.yaml"
kubectl apply -f "$MIGRATION_DIR/audiomuse-database.yaml"
```

These offline exports include only the reviewed PostgreSQL StatefulSet, Service,
fresh claims and its required scripts/runtime/registry Secrets. They contain
private data, use owner-only staging and refuse overwrite. Confirm the intended
claims are newly provisioned and the database is Ready, then perform the native
dump restore described in DATA-MIGRATION.md. Synapse/MAS/relay and media writers
stay held until database contents are verified. Qualify RBD snapshot creation
and fresh-PVC restoration, including the independent snapshot controller, before
releasing Forgejo's snapshot backup schedule. Update the separate application
CI workflow/branch requirements for retired native execution before starting
the Linux launcher; retain original signed source recovery evidence.

## 8. External providers, mail routing and backups

Export preserved provider state to private local files before plans, initialize
exact locked providers, and inspect plans with those files. Permit only the
reviewed identity state-name move/retired client changes; retain existing IDs,
DNS addresses, NetBird policies, AWS mail EIP/RDS/S3/IAM/Secrets Manager ownership.
Do not apply an empty-state plan. Propagate any deliberately changed outputs to
encrypted app inputs before reconciliation; do not generate new client secrets
as a shortcut for restoring original identity.

After a reviewed identity provider change, pipe its complete local outputs
directly into the encrypted credential renderer:

```sh
tofu -chdir=components/homelab/providers/identity output -json \
  | nix run .#render-cluster-credentials -- --identity-outputs-stdin
```

Use the prepared private state/backend context for this command. Do not write
outputs to ordinary files or terminal logs. The renderer validates all eight
retained client pairs, preserves signing/session keys and updates concrete
Forgejo, Grafana, media, Wallos and Matrix credentials. NetBird's client pair
updates the encrypted input for its independent provider; that provider's
reviewed apply updates the restored server's external identity registration.
The preserved Kubernetes client moves state addresses while keeping its ID.
If that ID deliberately changes, update the host AuthenticationConfiguration
and qualify API login separately before host activation.

Coordinate the new mail-admin egress path: apply reviewed RouterOS TCP 8080
rules for `.20.10/.20.11/.20.12` and the independent mail guest's matching
WireGuard AllowedIPs/nginx allowlist. Then verify HTTPS mail-admin from trusted
LAN/admin VPN and denial from untrusted clients. Public mail behavior remains
on AWS and needs its existing end-to-end readiness/restore checks.

Initialize the dedicated target etcd Restic repository once using the existing
private B2 environment and new `etcd_restic_password`; do not reinitialize an
existing repository or rotate its key during cutover. NixOS sets
`initialize=false` deliberately. On each host take a manual K3s etcd snapshot,
run `restic-backups-homelab-etcd.service`, verify the remote snapshot and restore
its payload independently. Require token, snapshot, TLS/cred, host age and SSH
key together, plus successful textfile metrics. The server token is necessary
for recovering encrypted K3s bootstrap data; see [K3s backup requirements](https://docs.k3s.io/datastore/backup-restore).

Verify Velero/Kopia, native CNPG, Forge snapshots, Matrix/AudioMuse dumps, games,
HA/Thread and UniFi Restic schedules against their declared destinations. Run
a new target backup and isolated restore after target data is qualified; an old
source backup proof does not qualify the new direct-CSI storage path. Monitoring
history is retained for cutover, but the current application Velero schedules
exclude `services-observability`; do not claim ongoing automatic history backup
without an implemented and qualified native monitoring backup.

## 9. Release the normal graph and retain recovery evidence

Check every retained function against the inventory: SSO/API roles; DNS/TLS;
Grafana/logs/alerts; all home devices; media/import/upload/playback; Wallos;
Forge SSH/HTTPS/LFS/packages/Actions/Linux cache/signing; Matrix local/federated
login/media/encrypted relay; NetBird routes/STUN; game worlds/ports; UniFi/APs;
independent mail/admin/backup. Compare source identities and representative
counts/bytes. Record deliberate retirements and all target restore/backup proofs.

After all holds are released and verified, change root sync to
`./deployments/homelab/cluster`, resume the root Kustomization and require every
child Ready. Ensure the Git revision actually declares the normal path and
that the recovery overlay will not reassert holds. Restore normal CronJobs and
runner scheduling only after this check. Archive execution changes and final
inventory in the reviewed Git/recovery records.

After final independent exports and source recovery archives are verified,
retire only the inventoried old RouterOS VLAN/API objects through the separate
phase, from the repository development shell:

```sh
cd components/homelab/network-automation
ansible-playbook reconcile-routeros.yaml --tags retire-legacy \
  --extra-vars migration_exports_verified=true
```

The ordinary `apply` tag does not select these deletions. The retirement phase
matches bridge/VLAN IDs and full filter identity; foreign or duplicate rows
cause refusal. Verify the target VLANs, API, private HTTPS and PiKVM access after
retirement. Keep the physical rescue path available.

Retire remaining source cloud VLANs, ACLs, DNS/certificates, provider keys,
guests/images and recovery-only object state only after the corresponding
retirement proof. Retain the independent source package through a recorded
recovery horizon and a successful target disaster-recovery drill. Delete old
B2/Kopia snapshots through their native lifecycle, not by deleting shared chunks.

## Rollback boundaries

Before SATA overwrite, resume the source from its recorded controller/replica
states after verifying VIP ownership; no app restore is needed if its final data
remains intact. After SATA overwrite but before NVMe reuse, source rollback
requires verified host OS/ESP and `/var/lib/rook` monitor/etcd/PKI recovery plus
the untouched old OSD FSID/devices. Restore those consistently; do not attach
old OSDs to the fresh target FSID or run both control planes.

After any NVMe is wiped or the target accepts writes, rebooting the old Ubuntu
OS does not restore the source cloud. Prefer forward recovery into the target
from the checked independent exports/native backups. A full source-cloud
rebuild would require its archived software, metadata, etcd, Ceph cluster and
every disk/image export, with much longer downtime. Preserve new target writes
before any reverse data move. An application failure should leave its stage
held and data intact while restoring that app in isolation; do not wipe the
entire target to repair one service.

For target K3s disaster recovery, restore one chosen etcd snapshot with its
matching server token on the first server using the pinned
`k3s server --cluster-reset --cluster-reset-restore-path=...` procedure, then
rejoin the other two after clearing their stale etcd membership as documented
upstream. Keep all other servers stopped until the first recovery completes.
This recovers Kubernetes metadata and Secrets; app volume/native database data
and Ceph monitor/OSD recovery remain separate requirements. Follow the
[K3s snapshot restore sequence](https://docs.k3s.io/cli/etcd-snapshot) with the
same critical cluster networking/token configuration; qualify it independently
before treating scheduled snapshots as a tested disaster-recovery system.

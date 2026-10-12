# Application data export and recovery

This is the future execution procedure for the prepared migration branch. No
writer has been stopped, volume copied, guest shut down or disk reformatted by
the preparation work. An inventory entry and an old successful backup are not
proof that the final source bytes have been exported and restored.

## Recovery model and complete scope

Restore into a fresh Rook cluster and freshly provisioned direct-CSI claims.
Keep the old NVMe devices untouched until the independent exports and test
restores pass. A Cinder/Manila PV handle belongs to the old cloud driver; editing
its driver or copying the old PV into the target does not migrate its data.
Never mount one database directory concurrently in two production instances.

`inventory-map.json` is the per-object ledger: 56 live claims, 74 PVs, 65 Cinder
devices, 11 Nova guests, 17 Glance images and the Manila share. A Cinder device
represented by a PV is one underlying source, not an additional independent
copy. Include released PVs and the nine unclaimed cloud devices: lack of an
attachment is not permission to discard their bytes. Qualification-only claims
can be rebuilt after recording their completed proof and source backup identity.
Only the identified native Windows/macOS boot devices/images have owner-approved
runner retirement. Application repositories, packages, job artifacts, signing
keys and Linux CI are retained.

The ledger must also cover sources outside those lists:

- Nova/libvirt ephemeral guest root disks and backing-image dependencies.
- Old physical host root/ESP disks, `/var/lib/rook` monitor state, Ceph FSID,
  mon/osd maps, keyrings, pool/filesystem/image/subvolume metadata and CRs.
- Every old cluster's etcd snapshot, matching PKI, kubeconfigs and bootstrap
  credentials, plus all twelve archived provider backend states.
- Public gateway TLS/private keys, ACME account, SSH identities, OIDC clients,
  database passwords, session/signing/encryption keys and radio datasets.
- Independent AWS mail recovery: existing RDS/S3/Secrets Manager resources and
  provider state remain in place; they are not local Ceph restore targets.

For every source record the source ID/handle, final quiescence time, export path,
format, allocated and used bytes, SHA-256, native backup ID/LSN where relevant,
target identity, restore result and reviewer. Keep the ledger with the private
recovery package, not with plaintext credentials in Git. Every source needs a
successful export/restore disposition or the explicit removal reason already
recorded in the inventory. Discoveries during execution update that inventory
before source retirement.

## Independent staging and command conventions

Use an encrypted external disk/NAS outside all three servers and their Ceph
cluster. Record its free capacity and measured source bytes before stopping
anything. The requested PVC sizes are reservation limits; the 1 TiB media claim,
800 GiB Forge backup claim, sparse guest images and released devices require
actual measurements. Allow room for exports, an independent backup and a test
restore. B2 alone is acceptable only after a full download/restore qualification
and a measured download window. A local Ceph snapshot does not survive wiping
the source Ceph cluster.

On the workstation, from the migration repository root:

```sh
umask 077
export MIGRATION_STAGE=/mnt/independent-encrypted-disk/homelab-migration
install -d -m 0700 "$MIGRATION_STAGE" "$MIGRATION_STAGE/claims" "$MIGRATION_STAGE/cloud" "$MIGRATION_STAGE/recovery"
df -B1 "$MIGRATION_STAGE"
export MIGRATION_SOURCE=/home/funforgiven/dev/infra
test "$(git -C "$MIGRATION_SOURCE" rev-parse --short=7 HEAD)" = 8d5f130
old_services() { nix run "$MIGRATION_SOURCE#matrix-access" -- services -- kubectl "$@"; }
old_infrastructure() { nix run "$MIGRATION_SOURCE#matrix-access" -- undercloud -- kubectl "$@"; }
target() { kubectl --kubeconfig "$TARGET_KUBECONFIG" "$@"; }
```

These wrappers deliberately select the frozen source or the explicit new
kubeconfig. The source wrapper is recovery tooling from the old revision; it
does not reintroduce a cloud controller into the target. Use a source checkout
at that revision if main has since advanced. Export kubeconfigs and recovery
keys to owner-only files through the existing SOPS mechanisms. Do not print
decoded Secret data or put passwords in arguments, shell tracing or logs.

## Repeatable source configuration capture

Use the repository helper before the outage for comparison, and again after
source reconcilers are suspended while their APIs and storage remain available:

```sh
nix run .#migration-source-capture -- \
  --source-repository "$MIGRATION_SOURCE" \
  --output-directory "$MIGRATION_STAGE/recovery/source-capture-final"
```

The source checkout must have the exact recorded source commit and no tracked
edits. The command uses that checkout's `matrix-access` wrapper for authenticated
GET requests. OpenStack SDK use stays in the source environment. Capture is
read-only: it neither freezes writers nor changes either checkout, provisions
resources or exports application data. Choose a new directory on every run;
files are mode 0600, the directory is 0700, and overwrite is refused. Only a final
`capture-manifest.json` with `complete: true` establishes a successful capture.
A failed or interrupted directory is incomplete and must not be used for cutover.

The command captures both source infrastructure and services clusters' Secrets,
ConfigMaps and controllers directly into SOPS ciphertext, plus compatible
runtime/provider and certificate/account archives. Plaintext allowlisted files
record PVC/PV IDs, controller replicas/suspension, service addresses, certificate
fingerprints/expiry and provider lineage/serial. Paginated cloud GETs cover
Nova, Cinder, snapshots, Manila exports, Glance, floating IPs and their actual
Neutron/Octavia owners. API failures, missing required state/runtime inputs,
pagination loops and foreign pagination endpoints fail capture. The manifest
records source revision, start/end times, counts and artifact hashes. The package
contains sensitive recovery material even though private values are encrypted;
retain it on independent staging and keep recipient keys recoverable.

Review changes against the prepared `live-*.json` inventories and update every
new/missing source disposition before disk reuse. Review certificate ownership
first, then update known fingerprints/expiry in `certificate-plan.json` from the
fresh inventory; preserve each reviewed action/target and explicitly disposition
new objects. Pass the fresh certificate archive with `--snapshot` to
`migration-certificate-bundle`. For provider exports, pass the fresh
`migration-state.sops.yaml` with `--snapshot`; compare retained lineages/serials
before planning. Refresh concrete target credentials from the reviewed fresh
runtime inputs before installation. This command deliberately does not replace
prepared Git inputs or automatically assign retirement/restore actions.

The CAPI management cluster's etcd/PKI, physical root/ESP and Ceph monitor-state
archives remain separate mandatory exports described below. A configuration
capture contains no volume bytes, native DB backup, guest image or physical-host
recovery archive. Do not apply its full source Secret/controller archives to the
target. Preserve them for source recovery and review.

## Freeze and final backups

Suspend all source Flux Kustomizations and HelmReleases before manually changing
workload replica counts. Stop in-cluster provider and guest-provisioning
reconcilers as well; otherwise they can replace guests or undo shutdowns. Record
replicas, CronJob suspension and controller states in the recovery package.
Disable app schedulers/runners, inbound writers, music importers and game saves
in the final downtime window. Keep databases running long enough to take their
native backups. Check for active Jobs and connected external clients, then
stop them or let them finish. Keep source storage and its controllers available
until exports finish.

Example suspension, repeated against each old cluster using its wrapper:

```sh
old_services -n flux-system get kustomizations -o name |
  while read -r resource; do old_services -n flux-system patch "$resource" --type=merge -p '{"spec":{"suspend":true}}'; done
old_services get helmreleases -A -o json |
  jq -r '.items[] | [.metadata.namespace,.metadata.name] | @tsv' |
  while IFS="$(printf '\t')" read -r namespace release; do old_services -n "$namespace" patch helmrelease "$release" --type=merge -p '{"spec":{"suspend":true}}'; done
```

Suspend production CronJobs before final data captures. Take native database
backups and flush/stop each application before its cold filesystem export.
Finally shut down UniFi and all VM/control-plane writers before raw-device
exports. Shutting down the cloud APIs comes last, after all mappings and exports
have been verified. Schedule suspension is not a guarantee that already-running
Jobs stopped.

## Filesystem claims: repeatable cold export and restore

The offline `migration-volume-plan` app renders a temporary transfer Pod for an
inventoried source claim. Export mounts are read-only, with no service-account
token. For a restricted namespace, record the current Pod Security enforcement
labels, temporarily permit the administrative root transfer Pod while all app
writers are held, and restore the exact enforcement labels before app release.
A root tar restore cannot pass restricted Pod Security; do not leave an exception
in the normal namespace declarations. Baseline namespaces permit the selected
capabilities, and privileged namespaces need no temporary change. The pinned Ceph utility image supplies GNU tar. Its image, tar support,
namespace admission and storage detach behavior must pass the isolated pilot
before the general export. This helper never calls a cluster or copies bytes.

Example for Wallos after its writer has stopped and its RWO attachment detached:

```sh
nix run .#migration-volume-plan -- --source-cluster services --namespace finance \
  --claim wallos-database --direction export > "$MIGRATION_STAGE/export.yaml"
old_services apply -f "$MIGRATION_STAGE/export.yaml"
old_services -n finance wait pod/migration-copy --for=condition=Ready --timeout=10m
old_services -n finance exec migration-copy -- du -sx -B1 /data
old_services -n finance exec migration-copy -- \
  tar --numeric-owner --acls --xattrs --sparse -C /data -cpf - . \
  > "$MIGRATION_STAGE/claims/services-finance-wallos-database.tar.partial"
mv "$MIGRATION_STAGE/claims/services-finance-wallos-database.tar.partial" "$MIGRATION_STAGE/claims/services-finance-wallos-database.tar"
sha256sum "$MIGRATION_STAGE/claims/services-finance-wallos-database.tar" \
  > "$MIGRATION_STAGE/claims/services-finance-wallos-database.tar.sha256"
tar -tf "$MIGRATION_STAGE/claims/services-finance-wallos-database.tar" >/dev/null
old_services -n finance delete pod migration-copy --wait=true
```

Run with `set -euo pipefail`; never rename a failed stream. The sequential Pod
name intentionally prevents overlapping transfers in one namespace. A read-only
transfer mount is not a database-consistency mechanism: stop writers first.
Measure logical and allocated bytes, count files and record representative
content hashes. Preserve numeric ownership, permissions, ACLs, xattrs, hardlinks
and sparse files. Test extraction on a compatible filesystem independently.

For the target, keep the owning Flux stage suspended. Create the target namespace
from the root declarations and provision a new claim, including implicit chart
or StatefulSet claim names:

```sh
nix run .#migration-volume-plan -- --source-cluster services --namespace finance \
  --claim wallos-database --direction restore --new-claim > "$MIGRATION_STAGE/restore.yaml"
target apply -f "$MIGRATION_STAGE/restore.yaml"
target -n finance wait pod/migration-copy --for=condition=Ready --timeout=10m
sha256sum -c "$MIGRATION_STAGE/claims/services-finance-wallos-database.tar.sha256"
target -n finance exec -i migration-copy -- \
  tar --numeric-owner --same-owner --same-permissions --acls --xattrs --xattrs-include='*' --sparse \
    -C /data -xpf - < "$MIGRATION_STAGE/claims/services-finance-wallos-database.tar"
target -n finance exec migration-copy -- sync
target -n finance delete pod migration-copy --wait=true
```

Extract only into the reviewed empty target claim; a source's old PV name,
claim binding, CSI handle and owner references are never transferred. Confirm
restored counts/hashes and UID/GID before starting the app. The helper uses the
declared target CephFS RWX spec for media and direct RBD for block-backed files.
It refuses CNPG replica-directory restoration and archive/qualification-only
sources. Database data claims for Matrix/AudioMuse are freshly initialized by
their native PostgreSQL version and restored logically, not untarred as PGDATA.

For the media library, export the complete Manila filesystem, including hidden
files and Beets organization. The captured share ID is
`fcbda35a-8a7e-443c-97fa-5f9732a1ba85`; its source NFS export is in the cloud
inventory. Restore to `media/media-library` (`ceph-filesystem`, RWX, 1 TiB).
Keep library writers stopped while checking the Beets/SFTPGo/Navidrome references.

## Native databases and app-specific state

`migration-database-bootstrap` exports a private database-only bundle for Matrix
or AudioMuse without cluster calls. It selects PostgreSQL and its required
claims, scripts and Secrets from the exact Kustomize result, preserving pinned
images and generated ConfigMap names. Application writers/CronJobs are omitted;
the Flux stages must stay held. See RUNBOOK.md for the future apply sequence.


| Source | Final export and target recovery | Required integrity proof |
| --- | --- | --- |
| ZITADEL PostgreSQL 18 | Complete a CNPG plugin base backup and archive all WAL through the final application commit. Keep the source B2 prefix untouched. The target `identity/zitadel-postgres` bootstraps through `zitadel-migration-source` and writes future backups to `nixos-v1/`. Preserve masterkey, login-service key, passwords and original OIDC IDs. | Isolated recovery, organization/users/roles/clients counts and authenticated login; source backup ID, timeline and final LSN reached. |
| NetBird PostgreSQL 18 | Same native CNPG process, including `netbird`, `netbird_events` and `netbird_auth`. The target's recovery ObjectStore reads the original prefix; future backups use its `nixos-v1/` prefix. Preserve account/policy/operator tokens and provider state. | Account/peer/group/policy identities, device reconnection and routes/DNS; all three databases restored. |
| Matrix PostgreSQL 17 | Stop Synapse/MAS/relay writers, execute the existing dump hook in the database pod, export complete dumps and manifests. Initialize only the target PostgreSQL workload and its existing roles/credentials; restore both `synapse` and `mas` with `pg_restore --exit-on-error --clean --if-exists --no-owner --role=<app-role>`. App Pods remain stopped. | `pg_restore --list`, restore in an isolated PG17 instance, table/room/user counts and functional login. Preserve Synapse/MAS signing/session keys, media, relay queue, matrix-nio crypto stores and the encrypted canary. |
| AudioMuse PostgreSQL 15 | Run final `audiomuse-postgres-backup` Job, verify and export its dump plus checksum, initialize only target PG15 and restore with matching owner/password. The cold PGDATA copy is additional recovery evidence, not the default native restore. | List and restore the dump, verify analysis/library counts and AudioMuse→Navidrome access. |
| Forgejo | Cold-export all `forgejo-data` and retained `forgejo-backups`; preserve repositories, SQLite/WAL, LFS, packages, job artifacts, signing/runtime keys and Atollion recovery refs. Restore cache and descriptors separately. | SQLite `integrity_check`, Git `fsck`, LFS/package/artifact samples, SSH and HTTPS clone/push, signing identity, Linux CI/cache and existing restore verifier. |
| Wallos | Cold database and logos exports; preserve OIDC client and full SQLite files including any WAL/SHM captured after shutdown. | SQLite integrity, subscription counts, uploaded logos and OIDC login. |
| Media | Cold library and every Navidrome/Beets/SFTPGo/Discord persistent directory; preserve password-encryption/cookie/OIDC keys and Discord bot identity. Redis is transient; recreate it. | SQLite integrity, media samples, playlist/library references, authenticated streaming/upload and Discord playback. |
| Factorio/Valheim | Request final game save, stop server, export complete worlds/config/mods and backing claim. Rebuild only disposable restore-test claims. | Start isolated with no public listener, load world and inspect server identity/mods; then verify retained public ports. |
| Home automation | Stop HA/Matter/MQTT/Zigbee and OTBR after native backups; export all four state/backup claims. Preserve `.storage`, Matter fabric keys, MQTT persistence, Zigbee PAN/network key/coordinator state, Thread active/pending datasets and radio credentials. | JSON/SQLite integrity, existing HA user/integration/device identities, same Zigbee and Matter networks and a successful Thread/Matter device operation. Never reset/re-pair radios as a migration shortcut. |

For CNPG create a final `Backup` using the source ScheduledBackup's exact plugin
configuration and wait for `status.phase=completed`; record its `status.backupId`.
Force/verify final WAL archival on the source primary after application writers
stop. A new base backup without the final WAL is incomplete. The prepared target
restores through native plugin recovery, with three newly created replica PVCs.
For deterministic replay, record the source backup ID and final reachable
restore point and set `spec.bootstrap.recovery.recoveryTarget` in the reviewed
cutover configuration before creating the target Cluster. An isolated restore
must reach it and verify application data. The source prefix is read-only during
target execution; do not let target retention prune source backups. See the
[CNPG recovery procedure](https://cloudnative-pg.io/docs/1.28/recovery/).

Concrete final logical backup triggers after application writers stop:

```sh
old_services -n matrix exec statefulset/matrix-postgres -c dumps -- python /scripts/backup.py
old_services -n media create job --from=cronjob/audiomuse-postgres-backup migration-final-audiomuse
old_services -n media wait job/migration-final-audiomuse --for=condition=Complete --timeout=30m
```

Export the dump claims only after those succeed. Database bootstrapping must be
done while the app Flux stage and all application consumers remain held; do not
release a whole stage merely to initialize an empty database. Restore roles,
extension availability and ownership with the matching database version. The
Matrix initializer migrates its two managed pg_hba rules to `10.100.0.0/16`,
preserving local and custom operator rules. Home Assistant similarly migrates
only the known old proxy CIDR, preserving custom HTTP options and pairing state.

## UniFi and other cloud block devices

The active UniFi guest is Nova `294f80d3-6e79-4760-a527-29f49296938f`, booting
64 GiB Cinder device `a7dbe35a-ddfa-41fe-ae76-13481f3bc8c6`. It becomes one
supported Ubuntu 24.04 KubeVirt guest at the retained `10.21.40.127` address.
Take a native UOS backup and the existing Restic controller archive as well as
the complete cold boot-device export. Preserve `/var/lib/containers`, UOS host
configuration/identity, origin CA/server TLS, poller environment, backup password,
SSH host keys and the bootstrap-version sentinel. Preserve AP adoption; do not
run two copies connected to AP VLANs.

After a clean guest shutdown, identify the actual backend RBD image through the
source Cinder/Nova/libvirt configuration. Record its pool, namespace, image ID,
snapshots, size and parent/backing dependencies. Do not guess `volume-<UUID>`
from naming convention alone. From an authenticated source Ceph client:

```sh
rbd info "$SOURCE_RBD_IMAGE" --format json > "$MIGRATION_STAGE/cloud/unifi-rbd-info.json"
rbd status "$SOURCE_RBD_IMAGE"
rbd export --export-format 1 "$SOURCE_RBD_IMAGE" "$MIGRATION_STAGE/cloud/unifi-root.raw.partial"
mv "$MIGRATION_STAGE/cloud/unifi-root.raw.partial" "$MIGRATION_STAGE/cloud/unifi-root.raw"
sha256sum "$MIGRATION_STAGE/cloud/unifi-root.raw" > "$MIGRATION_STAGE/cloud/unifi-root.raw.sha256"
qemu-img info --output=json "$MIGRATION_STAGE/cloud/unifi-root.raw"
```

Raw export reads the logical image including parent data; it is independent of
the old backing image. Archive snapshot history separately where it represents
retained recovery points. For every other Cinder device and ephemeral Nova root,
repeat the backend identification/export and retain the individual proof. A
guest with an empty Cinder attachment list can still have a Nova image root in
RBD or a host-local qcow2 backing chain. Export/flatten all required backing data
while the guest is stopped and the source storage still exists. Download every
retained source Glance image needed for cloud rollback with its ID/checksum.
Released/unclaimed volumes remain independent archives until their contents and
historical owners are reviewed. See [Ceph RBD export](https://docs.ceph.com/en/latest/man/8/rbd/).

Before the first target UniFi boot, work on a copy of the exported disk with
libguestfs offline. Disable stale source cloud-init datasource/network overrides,
remove only source-generated Netplan definitions that match the old Neutron
NIC, and run cloud-init clean against the mounted guest without resetting SSH,
UOS/controller identity or machine-id. Preserve the bootstrap-version sentinel
so cloud-init does not reinstall over the restored controller. Inspect the new
NoCloud data: its two NIC MACs are fixed in `vm.yaml`; services NIC owns `.127`
and has the preferred default route, pod masquerade NIC provides the fallback.
Keep a pristine checksum-verified source export; record all changes in the copy.
The [cloud-init clean options](https://docs.cloud-init.io/en/latest/reference/cli.html)
explain the cache/seed reset. Check installed Ubuntu cloud-init's supported
options before invoking them offline.

Provision only the `unifi/unifi-root` 80 GiB filesystem claim and a transfer Pod,
with the VM held. Copy the prepared **raw** file into its filesystem root as
`disk.img`, verify SHA-256 in the mounted claim, then set owner/group `107:107`.
Do not import a qcow2 file as a raw disk or write the raw guest onto the entire
filesystem PV block device. The 64 GiB guest disk fits inside the 80 GiB claim;
guest root expansion is a separate reviewed operation after recovery. These
format/name/ownership requirements come from the [KubeVirt volume documentation](https://kubevirt.io/user-guide/virtual_machines/disks_and_volumes/).

## Monitoring history, silences and source cloud recovery

Cold-export the original workload Prometheus 20 GiB claim, Alertmanager 2 GiB
claim, physical Grafana 10 GiB claim and Loki 50 GiB claim into their mapped
`services-observability` targets. Record original UID/GID and software versions.
The two old physical Prometheus 50 GiB replica claims are separate preserved
history archives. They are not merged into the new 20 GiB active TSDB; an
isolated old-version reader can inspect each archive later without production
scrapes or alert delivery. Preserve WAL and complete TSDB blocks in each cold
archive. Grafana's SQLite/plugin data and Loki index/chunks restore together.

Capture silences from both old Alertmanager APIs before shutdown into private
JSON, with checksum and time. Archive all three old physical Alertmanager data
claims. Restore the workload claim into the target single replica, then import
still-active missing silences via the Alertmanager API, deduplicating by matcher
set, start/end time, creator and comment. Do not merge unrelated binary state
directories or replay duplicate notifications. Validate silences and route a
test alert through the retained Telegram/Matrix receivers.

Archive cloud MariaDB/OVN/RabbitMQ state and metadata with the source control
plane; those functions have explicit retirement reasons and no active target
database. Preserve Ceph maps/keyrings/FSID and cold `/var/lib/rook` monitor
directories plus host root/ESP images and all old etcd/PKI recovery packages.
Whole-root images must be taken from a consistent offline filesystem or verified
filesystem snapshot, not a raw copy of a changing mounted OS. Secret-bearing
archives stay encrypted off-server. Keeping OSD devices alone does not recover
lost monitors, keys or cloud metadata.

## Certificates, provider state and acceptance

`certificate-plan.json` gives every one of the 54 captured TLS/account/provider
objects an explicit action. The offline `migration-certificate-bundle` exports
only the three gateway TLS Secrets and ACME account into a new mode-0600 file
outside Git, checks expiry, keys, desired hostnames and public SHA-256 captures,
and refuses overwrite. Seed it before the gateway/Issuer stage; cert-manager
then owns certificate renewal. The active Flux credentials do not contain a
saved gateway TLS payload. Cluster webhooks, DB transport CAs and API certificates
regenerate; the independent ZITADEL login key remains encrypted app identity.
Do not apply the full source Secret archive as a Kubernetes bundle.

Export all four retained provider states with `migration-provider-state` into
private local state files before any provider plan. Compare final source state
lineage/serial with the certificate/state archive and refresh the migration
snapshot before cutover. Preserve existing resource IDs and sensitive outputs;
review the `undercloud`→`homelab` Kubernetes OIDC state move and every proposed
change. Reject plans that recreate identities, DNS records, AWS mail resources
or NetBird account/policies during data recovery.

Before any source SATA overwrite or Ceph NVMe reuse, all required final exports
must have checked hashes, independent readable copies and isolated app/native
database restore proofs. Record available staging capacity, coverage of every
inventory source, final DB positions, private-key recovery and source rollback
package completeness. Only then follow [RUNBOOK.md](RUNBOOK.md). After target
qualification, take and restore a new off-server backup from the target, retain
the source package, and retire only the items with recorded dispositions.

The nonsecret ownership audit in `provider-state-audit.json` accounts for all
twelve archived backend states. The four retained exports match the newer
capture lineage/serial; the earlier services-identity state is empty. Historical
OpenAI/Hermes state has eight external resource groups but no active reconciler
in the source revision. Keep that state encrypted and leave those resources
unchanged; cloud retirement does not authorize deleting unrelated external
resources. Refresh all retained state again for the actual cutover.

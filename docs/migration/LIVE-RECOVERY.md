# Live recovery — 14 October 2026

The approved outage replaced Ubuntu/OpenStack on Pecorino, Taleggio and Asiago
with the reviewed NixOS/K3s systems. Each booted its exact signed preparation
revision `c5df8795debbcc8c0f5989f2a664cf6ca8ba091e` from mirrored SATA.
SSH host identities and the operator/host recovery recipients were preserved.
PiKVM installation media is detached. Taleggio Secure Boot was disabled with
explicit owner approval; its PK/KEK/db/dbx variables were preserved.

OpenStack, Magnum, CAPI, guest Kubernetes clusters and their storage wrappers
are retired. Cilium 1.20.2 supplies networking; direct Rook-Ceph owns six NVMe
OSDs with three physical failure domains. The new Ceph FSID is
`56a911e8-2956-4a65-a211-263a30881a09`. The old cluster was archived and was
never adopted. Reusing the source NVMe disks ended simple on-disk rollback.
Recovery now relies on the independently downloaded Backblaze exports.

## Preserved data and bindings

All 50 retained source claims passed independent downloads and native recovery
checks before source reuse. The archives also preserve the three physical
roots/boot filesystems/two EFI roles, old etcd clusters, Ceph MON/OSD metadata,
guest disks, cloud control databases, released devices and historical assets.
Twenty-four filesystem transfers matched all recorded contents, numeric owners,
modes, links and xattrs before application writers were released. Target claims
use new Kubernetes UIDs and new CSI handles; their namespace/claim names and
application mount paths remain declared in Git.
The [binding record](TARGET-VOLUME-BINDINGS.json) records all 34 production
claims, their new PV/CSI identities, and recovery methods. It is evidence, not
a manifest to apply. Twenty-four qualified filesystem bindings still match
their restore proofs; eight PGDATA claims use native database recovery, UniFi
has its recovered guest disk, and the qualification canary is newly seeded.

Zitadel and NetBird recovered through their native base/WAL archives into new
three-replica CloudNativePG clusters. All persistent table counts, owners and
native index checks passed. Fresh target backups then passed independent native
restores. Matrix and AudioMuse recovered through their native logical dumps;
physical source PGDATA was never copied into a new major version.

The original UniFi disk was restored byte-for-byte into a new filesystem-backed
RBD claim. Its guest identity, owner/controller state and both AP adoptions
remain. Home Assistant retains its installation UUID, integrations, entities,
users, Zigbee network/coordinator and Thread dataset. Multus/macvlan rebuilds
its tagged IoT attachment with the declared IPv4/IPv6 addresses; native radio,
MQTT/Matter and passive multicast checks passed.

## Runtime checks already passed

- Fresh Ceph: native HEALTH_OK, three MON quorum, six OSDs up/in, replica 3/min 2,
  active/standby MDS, and MON/OSD traffic on VLAN 30.
- CSI: RBD write/hash across nodes, snapshot/clone, expansion and filesystem
  growth; CephFS concurrent RWX and cross-node remount.
- Cilium: native suite, 56 tests and 463 actions.
- Identity: original controller RSA authentication, roles, Kubernetes OIDC
  audience, all eight client ID/secret pairs and wrong-secret controls.
- Media: SQLite integrity, 508 tracks/63 albums/two users/eight playlists,
  authenticated native download matching the stored audio SHA-256, original
  SFTPGo administrator and owner inbox.
  An independent current library restore matched all 683 original file hashes
  (16,153,085,527 bytes), including library, staging and quarantine. Of the 508
  catalog records, 353 had files in the original library; the other 155 paths
  were already absent in the original sealed export. Their catalog records
  remain preserved. This is an existing source inconsistency, not migration
  data loss.
- Wallos: fresh native SQLite backup integrity, one user/ten subscriptions,
  HTTPS health and denied database/journal download paths.
- Forgejo: preserved private repository/API access and a new successful Linux
  checkout/isolation/local-build/artifact workflow on the infra qualification repo.
  The original pull credentials also authenticated the three retained private
  runtime/cache/runner image digests over HTTPS; native manifest and configuration
  blob hashes matched, independently of the nodes' cached images.
- Matrix: original relay user/device/token, joined rooms and MAS issuer.
- NetBird: original database account/policy/DNS ownership, three ready routing
  peers on different hosts, management/signal/STUN/relay readiness, permitted
  private health, denied finance database access and required application login.
  The fresh NetworkResource adopted the exact old operator DNS record IDs.
- Games: native Factorio map load/authenticated RCON and Valheim UDP query on
  their original VIPs.
- Monitoring: restored Prometheus series and Loki sample hashes, healthy Grafana
  SQLite, authenticated original Grafana administrator and all 11 live probes.
- Independent AWS mail: original instance/EIP/RDS/S3 and mail daemon retained;
  fresh backup downloaded/verified. Only the administration gateway's source
  addresses changed, using a separately signed address-only appliance build.

The private execution receipts and their hashes are sealed in independently
downloaded encrypted Backblaze checkpoints. They contain exact target/source
UIDs, CSI handles, backup versions and native recovery results. Current external
provider ownership is documented in [PROVIDER-STATE.md](PROVIDER-STATE.md).

Checkpoint recovery was also tested without either cluster API or the temporary
audit credential file. The committed encrypted `secrets/backblaze.yaml`
contains the checkpoint age identity at
`undercloud.etcd_recovery.age_identity`; the scoped download credential is in
`deployments/homelab/cluster/infrastructure/velero/credentials.sops.yaml`.
Both decrypt with the existing personal age key kept outside these servers.
Those Git-hosted credentials independently listed, downloaded and decrypted a
checkpoint, verified every artifact hash, and recovered its signed Git bundle.

## Completed deployment and independent recovery

The normal Flux root and all 29 child stages reconciled at the signed migration
revision. Temporary recovery holds and runtime overlays were removed. The two
alerting Secrets moved to their permanent observability owner with their UIDs
and encrypted contents preserved. All 34 production claim UIDs and CSI handles
remained unchanged through that handoff.

A fresh full application backup completed after all services were released.
Independent Forgejo, Matrix, home-automation, finance and media restores passed
their native checks. The four monitoring snapshots were independently downloaded
and opened with native Prometheus, Loki, Alertmanager and SQLite readers;
original historical queries and Loki WAL replay passed. The Beets catalog and
native AudioMuse dump claims also passed independent CSI downloads, all original
catalog references, a fresh PostgreSQL 15 restore and native index checks.
Successful disposable restore copies and their volumes were removed.

All three hosts then produced new native etcd backups after the permanent graph
was running. Each was independently downloaded using credentials recovered from
the Backblaze-restored signed Git bundle. Snapshot hash checks, native etcd
restores, stored ownership/modes, token/TLS material, the new CA and preserved
host age/SSH identities passed. These snapshots capture the deployed application
graph; the final documentation-only commit follows those successful checks.

Daily CSI data-movement schedules now export the four monitoring volumes and
the passive Beets/AudioMuse dump claims to Backblaze. Short-lived media CronJob
Pods are excluded from filesystem backups. The native Matrix verifier checks
writable temporary copies of recovered SQLite snapshots while its restored
source claims remain read-only, permitting SQLite WAL/SHM bookkeeping.

The final encrypted execution checkpoint contains the signed source bundle,
current encrypted provider ownership, original recovery archive locators,
volume bindings and native acceptance receipts. Select the newest verified
checkpoint by Backblaze upload/version time under
`services/kubernetes/plugins/migration/20261012/`; local `/tmp` verification
copies are temporary working data. Keep the personal/offline age identities
and the existing backup credentials available independently of these servers.

Interactive human OIDC sign-in, a real player joining each game, a personal
NetBird device tunnel, and an externally delivered test notification have not
been exercised by the migration automation. Existing native identities and
protocols have been checked without impersonating the owner or sending mail.
Windows/macOS runners are retired by the owner's request. Atollion's actual
workflow is manual certification; its current policy permits ordinary local
validation/review without native runners. No Atollion source, protection or
approval rule was changed. Deferred native certification is not reported as a
pass.

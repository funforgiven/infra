# Backup and restore

## What protects what

- **PostgreSQL** (CloudNativePG: identity, NetBird, Matrix) goes to B2 with
  Barman Cloud; each cluster has its own restore test (`apps/*/restore-test.yaml`).
  CNPG data claims carry `velero.io/exclude-from-backup=true`.
- **Volumes** in the namespaces listed in `schedules.yaml` are CSI snapshots
  moved to B2 by Velero's data mover (Kopia). A snapshot is crash-consistent:
  SQLite, PostgreSQL, Home Assistant, Zigbee2MQTT, Matter, OTBR and Valheim
  recover from it as from a power loss, so they need no pause or archive. Opt a
  claim out with `velero.io/exclude-from-backup=true`.
- **Pre-backup hooks** exist only where a crash-consistent copy is not enough:
  Factorio saves a complete named world, the Matrix relay snapshots its queue
  and crypto store with an encrypted canary, Muse writes an online SQLite copy.
- **The CephFS media library** is the one Kopia filesystem backup (opted in on
  the Navidrome pod): a CephFS snapshot is exported through a full 1 TiB clone.

Not covered: other namespaces and opted-out caches. These off-site copies are
the only protection against losing the whole Ceph cluster. B2 has no Object
Lock and the in-cluster Velero key can delete under its prefix, so a compromised
cluster can destroy its backups: keep admin and restore keys outside it.

**Never initialise a new repository over the existing prefix** (`velero.yaml`).
After a rebuild, restore the credentials, release the `velero` stage and wait
for an `Available` BackupStorageLocation, the old backups and `Ready`
BackupRepositories before restoring. The AWS plugin pin is explained in `velero.yaml`.

## Monthly restore drill

`backup-qualification/restore-drill` (`restore-drill.py`) takes the newest
`Completed` `daily` backup younger than 26 hours and restores only its claims
from every scheduled namespace into `<namespace>-restore`. Those namespaces are
PSA-restricted and deny all traffic. Claims land on `ceph-block-restore`
(Delete reclaim, Immediate binding, so no consumer pod is needed). The drill
then runs every suspended `restore-verify` CronJob in them (`verifiers.yaml`,
Matrix's in `apps/matrix/restore.yaml`): no token, no network, read-only
volumes. They check the canary checksum, SQLite integrity of Forgejo, Home
Assistant, Navidrome, Beets, SFTPGo, Muse and Grafana, `git fsck` of every
Forgejo repository, Factorio save archives, the Valheim world, Zigbee2MQTT,
Matter and Thread state, and decrypt the relay canary with the restored crypto
store. Finally it deletes every restored claim and fails if any restored volume
kept a `Retain` policy (delete those PVs by hand).

It proves that B2, the Kopia repositories and data-mover restores work and that
the data is application-consistent; it does not start workloads, rebuild the
cluster or restore the media library (`backup.fahrican.com/restore-drill=skip`).
Run it on demand with `kubectl -n backup-qualification create job
--from=cronjob/restore-drill <name>`. A new namespace needs both schedules,
`NAMESPACES` in `restore-drill.py`, a `<namespace>-restore` namespace,
`restore-namespaces.yaml` and a verifier.

## Live restore

Order: Ceph, the Velero stage, CloudNativePG databases (app READMEs), volumes,
workloads; identity before the apps that use it. Per app: check the recovery
point with the drill, suspend its Flux Kustomization, stop its writers, delete
the damaged claims (Retain keeps their volumes), and restore the claims:

```console
velero restore create <name> --from-backup <backup> \
  --include-namespaces <namespace> \
  --include-resources persistentvolumeclaims,persistentvolumes --wait
```

To inspect a copy first, add `--namespace-mappings <namespace>:<namespace>-restore`
and `--resource-modifier-configmap restore-drill-modifiers`. Resume Flux and
pass the app's own checks before deleting the old volumes. Filesystem backups
(older `services-*` backups, the media library) restore only into a running
pod, so restore them together with their workload.

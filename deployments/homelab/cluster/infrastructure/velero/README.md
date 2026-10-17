# Velero backup controller

Velero writes homelab backups to the private
`fahrican-cloud-recovery` Backblaze B2 bucket under
`services/kubernetes/`. Other recovery data shares the bucket but uses
different prefixes and credentials.

Flux applies this controller after observability and before the backup
policy. The dependency order is declared in [`../../waves/stages.yaml`](../../waves/stages.yaml).

## Storage and credentials

Concrete runtime objects are SOPS-encrypted in this stage:

- `velero/velero-object-storage` contains the scoped B2 key in AWS credentials-file format.
- `velero/velero-runtime-values` contains bucket, endpoint, region and prefix.

Refresh these from reviewed local enrollment inputs with
`render-cluster-credentials`. Follow the
[credential procedure](../../../credentials/README.md); do not create a new
repository, and keep the separate restore credentials outside the cluster.

Velero uses Kopia filesystem backups with a node agent on every node. Forgejo
creates its own CSI-snapshot exports, which Velero copies. Two schedules also
move CSI snapshot data to B2; see the [backup schedules](../backups/README.md#schedules). The namespace is
privileged for kubelet host paths.

The B2 bucket uses server-side encryption and a 30-day lifecycle for hidden
versions under this prefix. Object Lock is disabled. The Velero key can list,
read, write, and delete within its scope, so a compromised homelab
credential can damage these backups. Keep the administrative and restore
credentials outside the cluster.

## Check the controller

Run these commands with the homelab kubeconfig:

```console
kubectl -n flux-system get kustomization velero
kubectl -n velero get helmrelease velero
kubectl -n velero get deployment,daemonset,pods
kubectl -n velero get backupstoragelocations.velero.io default
kubectl -n velero get backuprepositories.velero.io
velero backup get
```

The BackupStorageLocation must report `Available`. Every schedulable node must
have a Ready node-agent pod. A BackupRepository appears after the first
filesystem backup.

On-demand backup, inspection, and restore commands are in the
[backup and restore runbook](../backups/README.md).

## Alerts

The Helm release installs two critical alerts:

- `VeleroBackupFailed` fires when a scheduled backup reports a non-success
  status for 15 minutes.
- `VeleroNoRecentBackup` fires when `services-daily` has no successful backup
  within 26 hours, after a one-hour delay.

Velero metrics, node-agent metrics, and these rules are selected by the
Prometheus stack.

## Recovery and known compatibility issue

After rebuilding the homelab cluster, restore the reviewed concrete credentials
and release the Velero Flux stage after its dependencies are ready. Do not initialize a
new repository over the old prefix. Confirm that the BackupStorageLocation is
Available, that the stored backups are listed, and that the Kopia repository
is Ready before starting a restore.

The AWS object-store plugin is pinned by digest to the upstream `main` image
built on 2026-08-14. It contains commit `8dbd6b8`, which omits an empty
`x-amz-tagging` header rejected by B2. Replace it only with a tagged release
that contains the same fix. B2 request checksums are disabled for compatibility;
TLS transport and Kopia repository integrity checks remain in use.

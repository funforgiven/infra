# Velero backup controller

Velero writes services-cluster backups to the private
`fahrican-cloud-recovery` Backblaze B2 bucket under
`services/kubernetes/`. Other recovery data shares the bucket but uses
different prefixes and credentials.

Flux applies this controller after services observability and before the backup
policy. The dependency order is declared in [`../waves.yaml`](../waves.yaml).

## Storage and credentials

The undercloud services reconciler reads the destination from the
Git-managed `services-backup-destination` ConfigMap. It renders these two
runtime objects in the services cluster:

- `velero/velero-object-storage`, containing the scoped B2 key in the AWS
  credentials-file format;
- `velero/velero-runtime-values`, containing the bucket, endpoint, region, and
  prefix used by the Helm release.

The source credentials stay SOPS-encrypted. Do not edit either generated
object by hand; use the credential procedure in
[`../ACTIVATION.md`](../ACTIVATION.md).

Velero uses Kopia filesystem backups and deploys a node agent on every node.
Cinder and Manila snapshots are disabled, so recovery does not depend on
snapshots from the source OpenStack control plane. The `velero` namespace is
privileged only because the node agents need kubelet host paths.

The B2 bucket uses server-side encryption and a 30-day lifecycle for hidden
versions under this prefix. Object Lock is disabled. The Velero key can list,
read, write, and delete within its scope, so a compromised services-cluster
credential can damage these backups. Keep the independent administrative and
restore credentials outside the cluster.

## Check the controller

Run these commands with the services-cluster kubeconfig:

```console
kubectl -n flux-system get kustomization services-backup-controller
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
[backup and restore runbook](../16-backup-policy/README.md).

## Alerts

The Helm release installs two critical alerts:

- `VeleroBackupFailed` fires when a scheduled backup reports a non-success
  status for 15 minutes.
- `VeleroNoRecentBackup` fires when `services-daily` has no successful backup
  within 26 hours, after a one-hour delay.

Velero metrics, node-agent metrics, and these rules are selected by the
services Prometheus stack.

## Recovery and known compatibility issue

After rebuilding the services cluster, let the services reconciler recreate the
runtime Secret and ConfigMap, then let Flux install Velero. Do not initialize a
new repository over the old prefix. Confirm that the BackupStorageLocation is
Available, that the existing backups are listed, and that the Kopia repository
is Ready before starting a restore.

The AWS object-store plugin is pinned by digest to the upstream `main` image
built on 2026-08-14. It contains commit `8dbd6b8`, which omits an empty
`x-amz-tagging` header rejected by B2. Replace it only with a tagged release
that contains the same fix. B2 request checksums are disabled for compatibility;
TLS transport and Kopia repository integrity checks remain in use.

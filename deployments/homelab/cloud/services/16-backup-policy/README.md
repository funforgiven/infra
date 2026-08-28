# Backup and restore

Velero backs up the services cluster with Kopia filesystem backups. The policy
covers the `backup-qualification`, `media`, and `services-databases`
namespaces. Volume snapshots are not used.

## Schedules

| Name | Schedule | Retention | Purpose |
| --- | --- | --- | --- |
| `services-daily` | 02:30 UTC every day (`30 2 * * *`) | 720 hours (30 days) | Daily application backup |
| `services-weekly` | 03:15 UTC every Sunday (`15 3 * * 0`) | 2160 hours (90 days) | Weekly application backup |
| `restore-qualification` | `0 5 1 * *`, `Europe/Istanbul` | Latest restored namespace remains until the next run | Monthly B2 restore test |

The Velero controller runs the backup schedules in UTC.

AudioMuse's live PostgreSQL volume is excluded from filesystem backup. Its
`audiomuse-postgres-backup` CronJob writes a PostgreSQL 15 custom-format dump at
01:45 `Europe/Istanbul` to the `audiomuse-postgres-dumps` PVC and retains the
three newest dumps. Velero backs up that dump volume. Recover AudioMuse from a
dump, not from the empty restored live-data PVC.

## Run and inspect a backup

Run these commands with the services-cluster kubeconfig:

```console
velero backup create <backup-name> --from-schedule services-daily --wait
velero backup describe <backup-name> --details
velero backup logs <backup-name>
velero backup get --selector velero.io/schedule-name=services-daily
```

Use a unique lowercase name. Check that the backup is `Completed`, that every
expected PodVolumeBackup completed, and that no expected namespace or PVC is
missing.

## Automated restore check

The source `backup-qualification` namespace contains a 1 GiB `rbd1` PVC. Its
canary writes a fixed file only in that source namespace and verifies its
SHA-256 checksum whenever it starts.

On the first day of each month, the restore job selects the newest
`services-daily` backup. It fails if that backup is not `Completed`; it does not
fall back to an older backup. The job then:

1. deletes only `backup-qualification-restore` and waits for it to disappear;
2. restores `backup-qualification` into that namespace;
3. removes the backed-up PVC's `spec.volumeName` so `rbd1` provisions a new
   volume;
4. waits for the restore and the restored canary Deployment to complete.

The job cannot read Secrets or delete any other namespace. It leaves the
restored namespace available for inspection until the next run. Each run
downloads Kubernetes 1.36.2 `kubectl` and verifies its pinned SHA-256 checksum,
so access to `dl.k8s.io` is required.

Run the same check on demand with a unique Job name:

```console
kubectl -n backup-qualification create job \
  --from=cronjob/restore-qualification <job-name>
kubectl -n backup-qualification wait \
  --for=condition=complete job/<job-name> --timeout=90m
kubectl -n backup-qualification logs job/<job-name>
kubectl -n velero get restores \
  -l backup.fahrican.com/qualification=true
```

## Isolated media restore

Never test a media restore against production routes, mail relays, Telegram
bots, or identity callbacks. Create a disposable namespace and apply a deny-all
NetworkPolicy before creating the restore:

```console
kubectl create namespace media-restore
kubectl label namespace media-restore \
  pod-security.kubernetes.io/enforce=restricted \
  pod-security.kubernetes.io/enforce-version=v1.35 --overwrite
kubectl -n media-restore apply -f - <<'EOF'
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: deny-all
spec:
  podSelector: {}
  policyTypes:
    - Ingress
    - Egress
EOF
```

Restore a completed backup with the declared media PVC modifier:

```console
velero restore create <restore-name> \
  --from-backup <backup-name> \
  --include-namespaces media \
  --include-cluster-resources=false \
  --namespace-mappings media:media-restore \
  --exclude-resources httproutes.gateway.networking.k8s.io,services,cronjobs.batch,jobs.batch \
  --resource-modifier-configmap media-restore-modifiers \
  --wait
velero restore describe <restore-name> --details
velero restore logs <restore-name>
kubectl -n media-restore get pvc,pods
```

`media-restore-modifiers` removes every media PVC's production
`spec.volumeName`, allowing Cinder and Manila to provision isolated volumes.
Inspect representative audio and application files. Mount the restored
`audiomuse-postgres-dumps` PVC in a disposable PostgreSQL 15 environment, run
`pg_restore --list` on the chosen dump, restore it into an empty database, and
run representative queries. Use the checks in the
[`../40-media/README.md`](../40-media/README.md) for the rest of the media
workflow.

For a live recovery, first verify the selected recovery point in isolation.
Then quiesce every writer before replacing data, restore services in dependency
order, and reopen routes only after application-native integrity checks pass.

## Alerts and limits

The backup controller alerts on a failed scheduled backup and on the absence of
a successful daily backup for 26 hours. This policy adds:

- `ServicesRestoreQualificationFailed`, after a restore-check Job has failed
  for 15 minutes;
- `ServicesRestoreQualificationStale`, when no restore check has succeeded for
  40 days, after a one-hour delay.

The automated canary checks object-store discovery, namespace mapping, dynamic
PVC provisioning, node-agent access, Kopia transfer, and workload startup. It
does not validate application consistency or recovery after loss of the whole
OpenStack storage plane. Filesystem backups can capture changing application
files at different instants, so application-native dumps and isolated restore
checks remain necessary. The B2 prefix is not protected by Object Lock.

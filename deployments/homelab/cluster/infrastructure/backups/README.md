# Backup and restore

Velero backs up the single homelab cluster with Kopia filesystem backups. The policy
covers the `backup-qualification`, `finance`, `forge`, `games`, `home-automation`, `matrix`, `media`, and
`services-databases` namespaces. The application backup policy uses filesystem copies. Forgejo separately uses
temporary local direct-CSI snapshots to create portable recovery archives.
Separate daily CSI data-movement schedules export monitoring history and the
Beets/AudioMuse dump claims to Backblaze, including claims with no running Pod.
The application filesystem policy and native dump hooks continue separately.

## Schedules

| Name | Schedule | Retention | Purpose |
| --- | --- | --- | --- |
| `services-daily` | 02:30 UTC every day (`30 2 * * *`) | 720 hours (30 days) | Daily application backup |
| `services-weekly` | 03:15 UTC every Sunday (`15 3 * * 0`) | 2160 hours (90 days) | Weekly application backup |
| `observability-history` | 03:45 UTC every day (`45 3 * * *`) | 720 hours (30 days) | CSI snapshots exported to B2 for Prometheus, Loki, Grafana and Alertmanager |
| `media-passive-state` | 04:15 UTC every day (`15 4 * * *`) | 720 hours (30 days) | CSI snapshots exported to B2 for the Beets catalog and native AudioMuse dumps |
| `restore-qualification` | `0 7 1 * *`, `Europe/Istanbul` | Latest restored namespace remains until the next run | Monthly B2 restore test |

The Velero controller runs the backup schedules in UTC.

For an isolated PVC-only CSI restore into a `WaitForFirstConsumer` scratch
storage class, create an inert consumer after the restored PVCs appear. Velero
1.18 waits for the scheduler's selected-node annotation before provisioning
the temporary download volumes. Keep that consumer unprivileged, without a
service-account token, and inside the deny-all restore namespace. After every
DataDownload and the Restore complete, remove it before starting the offline
native database readers. Application restores normally supply their own
consumers; qualification must keep their production writers inactive.

AudioMuse's live PostgreSQL volume is excluded from filesystem backup. Its
`audiomuse-postgres-backup` CronJob writes a PostgreSQL 15 custom-format dump at
01:45 `Europe/Istanbul` to the `audiomuse-postgres-dumps` PVC and retains the
three newest dumps. The passive-state schedule backs up that dump volume even
when the dump Job has completed. Recover AudioMuse from a
dump, not from the empty restored live-data PVC.

Wallos creates an integrity-checked SQLite native backup every six hours. Its
Velero pre-backup hook refreshes that backup before Kopia copies the database
and uploaded-logo PVCs. Recover the database from `backups/wallos.db`, not from
the filesystem copy of the live `wallos.db`; see the
[Wallos runbook](../../apps/wallos/README.md).

`finance-restore-modifiers` removes the production volume bindings from both
Wallos PVCs during an isolated namespace-mapped restore. Exclude the live route,
workload, Secret, and NetworkPolicy resources so the restored financial data
cannot start a writer, receive traffic, contact ZITADEL, or send notifications.

Home automation uses a coordinated recovery archive instead of live database
copies. The backup hook gracefully stops its writers, archives their complete
state, resumes them, and validates file hashes and SQLite integrity. The monthly
`home-automation-restore` CronJob downloads the newest daily archive into an
isolated namespace and executes only the offline verifier. It cannot start
Home Assistant, MQTT, Zigbee or Matter. See the [automation runbook](../../apps/home-automation/README.md)
for the separate Thread dataset and activation requirements.

Matrix excludes its live PostgreSQL directory and creates logical dumps of
Synapse and MAS at 01:15 Istanbul and in a fail-on-error Velero pre-backup hook.
The relay hook snapshots its SQLite queue and crypto store, recording the bot
device identity and an encrypted recovery canary. Velero copies these recovery
sources and local media. A separate monthly `matrix-restore-qualification`
controller restores only Matrix PVCs and inert pods into the deny-all
`matrix-restore` namespace, restores both databases into disposable PostgreSQL,
checks queue integrity, and decrypts the canary with its recovered session.
See the [Matrix runbook](../../apps/matrix/README.md) for on-demand qualification,
SOPS recovery requirements and the coordinated live recovery sequence.

## Run and inspect a backup

Run these commands with the homelab kubeconfig:

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

The source `backup-qualification` namespace contains a 1 GiB `ceph-block` PVC. Its
canary writes a fixed file only in that source namespace and verifies its
SHA-256 checksum whenever it starts. Factorio's backup hook creates a completed
named save before the filesystem copy begins. Valheim's hook briefly stops the
game, archives the entire 1.0 world directory with a checksum, and resumes play
before the filesystem copy. Its archive is the coordinated recovery source.

At 07:00 Istanbul on the first day of each month, after the 05:30 daily backup,
the restore job selects the newest `Completed` `services-daily` backup whose
completion is less than 26 hours old. It fails if none qualifies. Unique restore
names let an on-demand retry validate the same backup again. The job then:

1. deletes only `backup-qualification-restore` and waits for it to disappear;
2. deletes `games-restore` through the same narrow resource-name permission;
3. restores `backup-qualification` and `games` into those two isolated
   namespaces;
4. removes the backed-up PVCs' `spec.volumeName` fields so `ceph-block` provisions
   new volumes;
5. gives the isolated sleepers small qualification-only resource requests;
6. waits for the restored canary Deployment and both game StatefulSets to become
   ready and verifies those resource requests were applied.

The restored Valheim container skips installation and gameplay, verifies its
recovery archive checksum and committed world marker, and only then becomes
ready. This checks archive integrity without launching a second public server.

The restored Factorio container detects that it is outside the production
`games` namespace and sleeps instead of starting a public server. Its integrity
sidecar tests every recovered save ZIP; the StatefulSet cannot become ready if
any save is corrupt. The restored Factorio container requests only 10m CPU and
64 MiB of memory while it sleeps, so leaving the latest restore available for
inspection does not reserve the production game's capacity. LoadBalancer
Services are excluded from the restore.

The job cannot read Secrets or delete any other namespace. It leaves both
restored namespaces available for inspection until the next run. Each run
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
`spec.volumeName`, allowing direct Ceph CSI to provision isolated volumes.
Inspect representative audio and application files. Mount the restored
`audiomuse-postgres-dumps` PVC in a disposable PostgreSQL 15 environment, run
`pg_restore --list` on the chosen dump, restore it into an empty database, and
run representative queries. Use the checks in the
[`../../apps/media/README.md`](../../apps/media/README.md) for the rest of the media
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
Ceph storage cluster. Filesystem backups can capture changing application
files at different instants, so application-native dumps and isolated restore
checks remain necessary. The B2 prefix is not protected by Object Lock.


The `observability-history` schedule runs at 03:45 UTC with 30-day retention.
It uses `snapshotMoveData` to export all four monitoring RBD volumes. Local
snapshots are temporary. Recovery must replay Prometheus/Loki WAL and check
Grafana SQLite integrity before accepting traffic. Each volume is a separate
crash-consistent recovery point; there is no cross-service atomic snapshot.

`media-passive-state` runs at 04:15 UTC with the same retention, selecting only
`beets-data` and `audiomuse-postgres-dumps`. CSI snapshot movement captures them
when their CronJob Pods have completed. Filesystem backup alone cannot cover
an unmounted claim. Recover AudioMuse from its native dump, and verify Beets
SQLite integrity plus its paths against the separately restored media library.

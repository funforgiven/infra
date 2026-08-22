# Backup policy and restore qualification

Daily and weekly Velero filesystem backups cover all authoritative Kubernetes
application namespaces. The backup-qualification namespace contains a small
Cinder PVC whose workload writes a deterministic canary only in the source
namespace. A monthly CronJob restores the newest successful daily backup into
backup-qualification-restore. The restored workload cannot become Available
unless the file arrived from object storage, which exercises backup discovery,
namespace mapping, PVC provisioning, the node agent, Kopia, and restore.

The job deliberately leaves the latest restored namespace available for
inspection and deletes only that fixed namespace at the beginning of its next
run. It cannot read Secrets and cannot delete any other namespace. Alerting
covers failed jobs and a restore-success age greater than 40 days.

This transport canary supplements rather than replaces application recovery.
Before resuming a stateful wave, and quarterly thereafter, restore that
application's latest backup into a disposable isolated cluster or namespace,
block all routes and outbound side effects, verify database-native integrity,
inspect representative records/files, and record the backup and restore IDs in
the operations log. Never point a qualification workload at production DNS,
mail relays, Telegram bots, or identity callback URLs.

Media namespace restores use the `media-restore-modifiers` ConfigMap as the
Velero `resourceModifier`. It removes each backed-up PVC's production
`spec.volumeName` so Cinder and Manila dynamically provision isolated restore
volumes. Create a deny-all ingress and egress policy in the mapped namespace
before the restore, and exclude HTTPRoutes and Services from the restore.

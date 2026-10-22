# One-time rollout steps

Steps needed once when this configuration first reaches the live systems,
because they need credentials or live state the repository cannot hold. Delete
each item when it is done, and this file when it is empty.

## Before merging to `main`

- **Matrix database backups.** `matrix-postgres` now archives to Barman Cloud
  and expects Secret `matrix/matrix-backup` (`ACCESS_KEY_ID`,
  `ACCESS_SECRET_KEY`, `AWS_REGION`, a B2 key for its prefix). Create
  `deployments/homelab/cluster/apps/matrix/backup.sops.yaml` and list it in
  that kustomization. Until it exists WAL archiving fails and
  `PostgresWALArchiveStale` fires; WAL then accumulates on the volumes.
- **etcd backups** moved to their own prefix `services/etcd/` so the Velero key
  can no longer delete host identities. Mint a key for that prefix (see
  [secrets](../secrets/README.md#edit-and-rotate)) and put it into
  `etcd_backup_environment` in `deployments/homelab/hosts/secrets.sops.yaml`
  before deploying the hosts; without it host backups stop and alert. After the
  first snapshot lands under `services/etcd/`, delete the old
  `services/kubernetes/nixos-etcd/` repository, which the Velero key can still
  read and delete.

- **`services-databases` namespace** is no longer declared and Flux will
  delete it with everything inside. Confirm it is empty first
  (`kubectl get all,pvc,secret -n services-databases`).

## OpenTofu

- Migrate each root's state from `secrets/current-provider-state.sops.yaml`
  ([providers](../components/homelab/providers/README.md#one-time-migration)),
  check that every plan is empty except the listed expected differences, commit
  the encrypted states, then delete the legacy file and the
  `migrate-legacy-state` command.
- `identity/moved.tf` exists only for the migration; delete it once the
  migrated identity plan is clean.
- `mail-aws` `bootstrap_revision` still names the pre-refactor commit; bump it
  to a signed commit of this design after merging, before any instance
  replacement.
- Apply `aws-iam` and attach the two role permission boundaries with
  administrator credentials before the next `mail-aws` apply; import the bucket
  into `backblaze`.

## Cluster, after Flux applies

- **Home Assistant** now loads Git-owned automations and the Rooftrollen
  dashboard from YAML. Delete the UI copies of the automations whose IDs are in
  `apps/home-automation/automations/` and the storage-mode
  `dashboard-rooftrollen`, restart Home Assistant, and publish empty retained
  payloads to the old `homeassistant/…/nuki_4e988f8f/…/config` discovery
  topics.
- **AudioMuse** imports its database into CloudNativePG cluster `audiomuse-db`.
  After AudioMuse works on it, delete the legacy `audiomuse-postgres`
  StatefulSet, Service, network policy, its data PVC and the old
  `audiomuse-postgres-dumps` PVC, and the `externalClusters` import source.
- **Backups.** Check that the first `daily` Velero backup completes with its
  data uploads, then run the restore drill on demand
  ([backups](../deployments/homelab/cluster/infrastructure/backups/README.md)).
  Restart Velero if `VeleroScheduleBackupStale` keeps firing for the removed
  `services-*`, `observability-history` or `volume-snapshots` schedules.
- **Matrix database** gains the Barman plugin, so CloudNativePG rolls all three
  instances with a switchover: schedule a short Matrix write interruption.
- **UniFi VM** gets its guest scripts from a new ConfigMap disk and inline
  cloud-init; restart it once (KubeVirt marks it `RestartRequired`) so the
  scripts install on boot.
- **Matrix restore pull secret.** `apps/matrix/registry-restore.sops.yaml`
  still names namespace `backup-qualification`; re-encrypt it for
  `matrix-restore` (or re-run `matrix-admin publish-image`), or the Matrix
  verifier cannot pull its image.
- **Forgejo** is `OnDelete`: delete its pod once to drop the removed backup
  sidecar.
- **Released volumes.** `ceph-block` retains volumes, so PVCs removed from Git
  leave Released PVs: `forgejo-backups` (its claim is unprunable; delete the
  claim first), `automation-backups`, `thread-backups`, `matrix-dumps`, volumes left by old
  restore checks, and the stale Valheim `/data/backups/recovery.tar`. Delete
  them once the new backups have run. The drill fails while Retain-policy
  volumes remain in a restore namespace.
- **`cnpg-system` namespace** is declared both in `cluster/namespaces.yaml` and
  `infrastructure/databases/namespaces.yaml` (identical, unprunable). Remove
  the second copy in a later change.
- **RouterOS.** Script errors now fail the playbook. Run it once in check mode
  (no tags) and fix any live drift it reports before `--tags apply`.

## Alerting

- Alerts are delivered to both Telegram and Matrix (`apps/matrix/rollout.json`
  phase `dual`). Once Matrix delivery is trusted, run `matrix-admin qualify`
  and `retire-telegram`, then delete `rollout.json`, those subcommands, the
  Telegram receiver and bot secret, and the Telegram notes in the secrets,
  observability and Matrix docs.

## Workstation

- Audio bridges now target the RØDECaster Duo's Expanded-mode outputs fixed in
  Nix; the Duo must be in Expanded mode.

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
  before deploying the hosts.

## OpenTofu

- Migrate each root's state from `secrets/current-provider-state.sops.yaml`
  ([providers](../components/homelab/providers/README.md#one-time-migration)),
  check that every plan is empty except the listed expected differences, commit
  the encrypted states, then delete the legacy file and the
  `migrate-legacy-state` command.
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
  StatefulSet, Service, network policy and PVCs and the `externalClusters`
  import source.
- **Released volumes.** `ceph-block` retains volumes, so PVCs removed from Git
  (old backup archives, the Valheim game install) leave Released PVs. Delete
  them once the new backups have run and a restore drill has passed.
- **`cnpg-system` namespace** is declared both in `cluster/namespaces.yaml` and
  `infrastructure/databases/namespaces.yaml` (identical, unprunable). Remove
  the second copy in a later change.
- **RouterOS.** Script errors now fail the playbook. Run it once in check mode
  (no tags) and fix any live drift it reports before `--tags apply`.

## Workstation

- Audio bridges now target the RØDECaster Duo's Expanded-mode outputs fixed in
  Nix; the Duo must be in Expanded mode.

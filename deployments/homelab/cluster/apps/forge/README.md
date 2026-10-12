# Private Forgejo and Actions

See [worker capacity and replacement](WORKER_CAPACITY.md) for the two Linux job slots, physical
node separation, resource budgets and maintenance.

Forgejo runs in the single NixOS/K3s cluster, with disposable Linux Actions jobs in `forge-ci`.
The private service is `https://git.fahrican.com`; Git SSH uses port `2222` on
the same services Gateway at `10.21.40.122`. Access is limited to the trusted
LAN, administration WireGuard network, and explicitly allowed service/runner
addresses. MetalLB announces the shared Gateway address; its Service uses
`externalTrafficPolicy: Local` to preserve client IPs.

## Identity and administration

Human accounts register through ZITADEL, which controls project access. The
provider requires a verified email and delegates MFA to ZITADEL. Forgejo does
not impose another local TOTP enrollment on OIDC accounts. Linking an existing
account requires authentication; matching an email does not automatically
take over an existing account. Accounts and repositories default to private.

Forgejo 15.0.7 formats boolean required claims with Go's `%s` verb. The pinned
bootstrap matches `%!s(bool=true)` for `email_verified`; false or missing
claims remain rejected. Recheck this workaround when upgrading Forgejo. Its
failure otherwise appears as an account suspension before account creation.

`forge-admin` is the local recovery administrator. Its password is encrypted
in `runtime.sops.yaml`. Keep the administrator UI and `/api/v1/admin` confined
to LAN/WireGuard; CI is explicitly denied these routes, including encoded
variants. The non-administrator `forge-runner` account owns the infrastructure
qualification repository and runner images. Human accounts remain separate.

Run the credential reconcilers from the repository development shell. SOPS
plaintext stays in captured pipes; only ciphertext is persisted:

```sh
python3 components/homelab/services/forge/enroll.py
python3 components/homelab/services/forge/enroll-runners.py
```

`runtime.sops.yaml` is excluded from Velero object metadata. Recover it from
SOPS and the services Flux age identity. Application secrets inside native
recovery archives are protected by Kopia encryption.

## Linux Actions

The qualification launcher checks the repository queue once a minute. Only
the init container sees a repository-scoped enrollment PAT. It creates an
ephemeral runner identity for one waiting job and passes that identity through
a memory volume. The job process cannot read the enrollment PAT, Kubernetes
credentials, or a Docker socket. Forgejo removes the identity after its job;
Kubernetes discards the writable container layer and workspace.

Labels are `linux-x86_64` and `linux`. Jobs run as UID 1000 with Nix, Node 24,
Git and standard build tools. Cilium policies allow only the documented
egress paths and deny metadata, cluster APIs, identity administration,
and other private networks. Each job has a two-hour limit and bounded CPU,
memory and ephemeral storage. The container registry credential can only read
packages and is held by kubelet, not mounted into job containers.

The qualification workflow in `components/homelab/services/forge/qualification.yaml`
checks private checkout, isolation, a Nix build, and artifact exchange between
two separate jobs. It runs weekly and retains its artifact for 45 days so
monthly recovery tests can verify real artifact bytes. Actions are pinned by
commit. These Forgejo jobs use the compatible artifact v3 protocol.

Build the Linux image with `nix build .#forge-linux-runner-image`, then publish
it with `components/homelab/services/forge/publish-runner-image.py`. Pin the
verified registry digest in `runners.yaml` before deployment.

Native Windows/macOS runner VMs and their brokers are retired for this target.
The retained Linux `windows-build` lane may cross-compile artifacts. Retiring
native execution requires updating the application's workflow and branch check
requirements through its normal reviewed change before CI scheduling resumes;
the infrastructure preparation does not modify that separate live repository.
Retain existing source validation and signed migration evidence for recovery.

## Backup and recovery

Compiler cache archives have a 64 GiB aggregate budget, with 16 GiB filesystem
headroom for uploads. The gateway evicts by least recent use and expires
archives unused for seven days or created more than 30 days ago. Maintenance
runs at startup and hourly even when no new uploads arrive. Active downloads
and recently accessed archives are protected by the gateway's existing lock
and reader tracking. Eviction causes a cold build; repository data, Actions
artifacts and native recovery images are stored separately. The 320 GiB cache
PVC stays provisioned; its thin storage allocation is reclaimed through the
worker's weekly trim policy rather than shrinking the filesystem in place.

`forge-snapshot-backup` runs every six hours. The existing Cinder CSI driver
captures a point-in-time snapshot of the single volume containing SQLite, Git,
LFS, packages, identity configuration, Actions logs and artifacts. A disposable
volume is restored from that snapshot. Only the clone is mounted by an isolated
exporter, which recovers/checkpoints SQLite's WAL, checks integrity, and writes
a portable tar archive with a SHA-256 completion manifest. Forgejo stays online.
Temporary exporter Jobs, the clone and the snapshot are deleted in that order;
owner references and the controller Job's TTL also cover interrupted cleanup.

Archives use uncompressed tar so Kopia can deduplicate unchanged contents
between exports. Keep the two newest completed local archives; prune only after
a successful new export and outside an active offsite backup. The pre-backup
hook also holds a one-hour retention lease to cover a prune Job already
starting when offsite backup begins. Kopia ignores unfinished `*.partial`
exports through its default `.kopiaignore` support. The native golden
images and migration recovery material have separate retention and are preserved.
The 800 GiB retained backup volume provides staging and recovery headroom; its
provisioned size is not the amount uploaded to Backblaze. Do not shrink it in place.

`backup.py` now serves recovery metrics. Its Velero `--once` hook checks that a
completed recovery source is less than eight hours old and never pauses the app.
The export controller has only namespace-scoped access to its Jobs, PVCs and
snapshots, plus read-only Velero backup status; the exporter has no Kubernetes
credential and no network access. A failed snapshot/export remains an alert,
while the application and existing recovery archives remain available.

Velero copies the backup volume using Kopia. Because the global policy uses
`defaultVolumesToFsBackup: true`, the pod explicitly excludes `data,tmp,control`;
the opt-in `backup-volumes: backups` annotation alone does not protect the live
SQLite/Git volume from that global opt-out policy. Offsite retention remains 30 days for daily and 90 days for weekly
backups. Recovery uses portable files and does not need the original OpenStack
cloud or any retained CSI snapshot. Old compressed archive chunks in Backblaze
expire with their retained backups and are reclaimed by Kopia maintenance;
changing the local layout does not immediately reduce the bucket's stored bytes.
Both legacy quiesced `.tar.gz` and online snapshot `.tar` manifests are supported
by the isolated restore verifier.

See [the September 10 online-backup recovery record](BACKUP_RECOVERY.md) for
the rollout, measured storage reduction and isolated Backblaze restore evidence.

Forgejo's single-replica StatefulSet uses `OnDelete` updates: applying manifests
must not automatically restart agents' Git/API connections or running CI.
Apply application/image upgrades during an explicit maintenance window. For a
backup-script-only update, protect the mounted bootstrap ConfigMap from pruning,
update its reviewed backup files in place and verify their hashes. During the
initial transition, run `legacy-backup-bridge.py` in that container: it holds
the old timer's maintenance lock and publishes real completion timestamps for
its existing metrics thread, without restarting any container or withdrawing
the pod's service endpoint. The compatibility status marker is excluded from
archive selection and retention. A later planned container/pod replacement
starts the new metrics-only process and needs no bridge. Remove the retained
old ConfigMap after the next planned Forgejo pod replacement. Do not delete or roll the Forgejo pod during active work.

Existing native image archives are source recovery records; no native image
publisher or native runner is deployed by this target. Their retirement and
the complete retained Forgejo data export are covered in
[DATA-MIGRATION.md](../../../../../docs/migration/DATA-MIGRATION.md).

The monthly `backup-qualification/forge-restore-qualification` CronJob restores
the latest completed daily backup into fresh `forge-restore` volumes. Its
service account can delete only the two test PVCs and the test pod. It also has
PV get/patch permission for cleanup: the code checks the restore label, scratch
StorageClass, namespace and claim UID, then uses conditional JSON Patch before
releasing a volume. Velero restores the source PV's `Retain` policy even when
the scratch class specifies `Delete`, so the policy must be corrected after
verification. Successful drills remove their pod and both disposable volumes;
failed drills remain for diagnosis. Completion is not reported until cleanup
finishes, and controller logs plus the Velero Restore retain the evidence. Cilium
explicitly denies all ingress and egress in that namespace. Restore modifiers remove
production bootstrap and replace application containers with verification
processes; no duplicate Forgejo or OAuth callback runs during the test. The
controller allows four hours for offsite transfer and verification, with a
five-hour Kubernetes Job deadline for cleanup and shutdown. The qualified
46 GB image set took about an hour to restore; review timeout and bandwidth
budgets when the retained data set grows.

Velero 1.18 requires `persistentvolumes` in the resource inclusion list even
for filesystem restoration. `includeClusterResources: false` and the PVC
storage-class/volume-name modifiers still prevent source PV rebinding. Keep
Velero's injected `restore-wait` init container when changing modifiers.

Qualification requires archive SHA256, SQLite integrity, an active ZITADEL
provider, Git object integrity, the qualification branch, successful Actions
history and exact artifact bytes. After Atollion cutover it also requires the
hashed `atollion-migration` source export, original issue/PR namespace and merge
history, all eight unfinished files in the checkpoint, distinct active agent
accounts, protected main and fast-forward-only merge settings. The Git verifier
requires both the original source and cutover commits to be ancestors of the
restored main branch and every original PR commit to exist.

The monthly target restore verifies the complete retained Forgejo application
scope. Native Windows/macOS images and firmware are excluded by the owner's
runner retirement. `--application-only` remains a compatibility flag; it no
longer narrows the target scope. Existing signed Atollion source qualification
history is retained; retiring native CI status requirements in the application
repository is a separate reviewed cutover step.

If `legacy-gitlab.json` is present, qualification also
verifies the retained native GitLab backup and recovery secrets. The retained
`legacy-gitlab-infrastructure` manifest additionally verifies the old backend
boot image and SOPS-encrypted cloud state checkpoints. The
`legacy-gitlab-object-store` manifest verifies the encrypted final export of
all remaining GitLab bucket objects, including the newest native backup.
Its retirement qualification separately restored, decrypted and checked every
object; the monthly verifier does not receive operator age keys. A Velero
`Completed` result alone is insufficient; both verifiers must become ready.
The target verifier checks retained application archives and historical GitLab
recovery manifests when present. Native-runner image recovery procedures are
dated source evidence in READINESS.md and ATOLLION-HANDOFF.md; they are not
requirements for the target application's monthly restore.

For actual disaster recovery, suspend `services-forge` reconciliation, restore
the backup PVC, verify a completed archive, then extract its `data/` contents
onto an empty Forgejo data volume with UID/GID 1000. Reconcile the original
SOPS runtime secrets and pinned image before starting Forgejo. Do not point
the isolated qualification modifiers at production. Resume Flux only after
private HTTP/SSH, OIDC and repository/Actions checks pass.

## Monitoring

Services Prometheus scrapes authenticated Forgejo metrics and backup freshness.
Rules alert on application unavailability, stale or missing native backups,
failed Actions launchers, jobs waiting over 15 minutes, unavailable queue
metrics, failed restores, and no successful restore in 40 days.
The existing Velero rules separately cover failed or overdue offsite backups.
Alerts use the services Alertmanager routing.

```sh
kubectl -n flux-system get kustomization forge
kubectl -n forge get pods,pvc,servicemonitor,prometheusrule
kubectl -n forge-ci get cronjob,jobs,pods
kubectl -n velero get backups,restores,podvolumebackups,podvolumerestores
kubectl -n backup-qualification get cronjob,job
kubectl -n forge-restore logs forgejo-0 -c database
kubectl -n forge-restore logs forgejo-0 -c git
```

## Migration handoff

The owner paused the Atollion agent and authorized migration on 2026-09-06.
The repository history is imported into private `funforgiven/atollion`.
Follow [ATOLLION-HANDOFF.md](ATOLLION-HANDOFF.md) for the import record,
separate agent identities, branch protection and remaining validation/cutover
sequence. The managed `gh` credential stays local; export uses the
repository-scoped CLI and an offline migration dump.
See [READINESS.md](READINESS.md) for the deployment and recovery evidence.
Atollion has two bounded Linux build slots with fresh 96 GiB disposable PVCs.
The Linux launcher retains a repository-scoped enrollment token; the generic
Linux qualification runner has a separate identity.
Application CI and recovery evidence must pass before resuming the paused agent.

The GitLab application and cluster have been retired. Retained recovery files
include its native backup, recovery secrets, backend boot image and encrypted
cloud state checkpoints, plus the final complete object-store export. The
dedicated project, network, GitLab flavors, image, load balancer, RGW service
and buckets have been deleted. The CI foundation retains the historical Terraform
controller name `gitlab-foundation` to preserve its existing state; that name
no longer provisions a GitLab service. Its source is
`components/homelab/services/forge/foundation-tofu` and its native flavor IDs are
preserved with explicit state moves.

Keep the retained recovery bundle and any older Restic objects under
`services/hosts/gitlab/` until their declared retention expires and the
replacement has been accepted. The
old Restic password stays SOPS-encrypted for historical recovery; removal of
its writer declaration must not delete the bucket's retained objects.

Historical GitLab deployment and recovery instructions are preserved at signed
revision `cc12dad6fc668158892239d1849b3cdeb8dd2891`, including
`deployments/homelab/cloud/gitlab/RECOVERY.md`. Use those files only for an
explicitly authorized, isolated historical recovery. The encrypted foundation
checkpoint includes the then-shared CI state: never restore it over the active
Forge CI Terraform backend. The current Forge service remains authoritative.

The final object-store export lives at
`/backups/legacy-gitlab-object-store/objects.tar.gz.sops.json`. Check its size
and SHA-256 against the adjacent `manifest.json` before recovery. An authorized
operator can decrypt it using an existing administrator or undercloud age
identity with `sops decrypt --input-type json --output-type binary`. The
resulting tar archive contains `manifest.json` and `objects/<bucket>/<key>`;
the inner manifest records each original object's size, SHA-256, ETag and
content type. It includes the newest native backup,
`1788653718_2026_09_06_19.3.1-ee_gitlab_backup.tar`, and its matching secrets.
Keep decrypted recovery material private. The supplementary offsite backup
and restore evidence are recorded in [READINESS.md](READINESS.md); subsequent
daily and weekly Forgejo backups include the same encrypted export.

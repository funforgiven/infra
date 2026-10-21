# Private Forgejo and Actions

Forgejo runs in the NixOS/K3s cluster, with disposable Linux Actions jobs in `forge-ci`.
The private service is `https://git.fahrican.com`; Git SSH uses port `2222` on
the same Gateway at `10.21.40.122`. Access is limited to the trusted
LAN, administration WireGuard network, and allowed service/runner
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
to LAN/WireGuard; CI is denied these routes, including encoded
variants. The non-administrator `forge-runner` account owns the
`runner-qualification` test repository and runner images. Human accounts are separate.

Run the credential reconcilers from the repository development shell. SOPS
plaintext stays in captured pipes; only ciphertext is persisted:

```sh
python3 components/homelab/services/forge/enroll.py
python3 components/homelab/services/forge/enroll-runners.py
```

`enroll.py` only generates Forgejo's local secrets. The ZITADEL OIDC client
(`forgejo-oidc-client-{id,secret}`) is written by
`render-cluster-credentials --identity-outputs-stdin`, with the other OIDC clients.

`runtime.sops.yaml` is excluded from Velero object metadata. Recover it from
SOPS and the cluster Flux age identity. Application secrets inside native
recovery archives are protected by Kopia encryption.

## Linux Actions

The `runner-qualification` launcher checks the repository queue once a minute. Only
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

The test workflow in `components/homelab/services/forge/qualification.yaml`
checks private checkout, isolation, a Nix build, and artifact exchange between
two separate jobs. It runs weekly and retains its artifact for 45 days so
monthly recovery tests can verify real artifact bytes. Actions are pinned by
commit. These Forgejo jobs use the compatible artifact v3 protocol.

Build the Linux image with `nix build .#forge-linux-runner-image`, then publish
it with `components/homelab/services/forge/publish-runner-image.py`. Pin the
verified registry digest in `runners.yaml` before deployment.

Only Linux runners exist; the `windows-build` lane cross-compiles.

Atollion has two Linux job slots. Each requests 4 CPUs and 4 GiB memory, with
limits of 6 CPUs and 6 GiB, and a fresh 96 GiB disposable workspace claim. The
`forge-ci` quota covers both slots and the `runner-qualification` runner: 9
requested CPUs/9 GiB and 16 CPU/16 GiB limits. The launcher requires the
`homelab.fahrican.com/ci-node=true` node label, prefers pecorino/asiago, and
uses pod anti-affinity on `kubernetes.io/hostname` so both jobs run on
different nodes. Limits do not reserve memory; check application, Ceph and node
usage before raising concurrency. CPU requests and the project's `CARGO_BUILD_JOBS`
are separate controls.

Drain one node at a time after checking etcd/Ceph quorum, volume health and
capacity on the other two. Finish or cancel active builds and hold the
launchers before normal Kubernetes eviction; never delete data or cache PVCs to
clear a drain. Afterwards check both job slots, artifact exchange, cache
restores and cleanup, then resume the launchers.

Atollion agents (`atollion-coordinator`, `atollion-worker-1` to `-3`) are
separate non-administrator Forgejo accounts, each with its own SSH signing key
and a PAT scoped to Atollion; credentials are encrypted in
`deployments/homelab/credentials/host-runtime/atollion-agents.sops.yaml`. A
signing key counts only after Forgejo's verification challenge. Renew agent web
sessions with `python3 components/homelab/services/forge/enroll-agent-sessions.py`.
Protected `main` requires signed commits, one whitelisted approval, an
up-to-date branch and fast-forward-only merges; only the owner and coordinator
merge. `atollion-agent-policy.json` is the merge policy also used by the restore
verifier. Merge signing uses the instance key in `signing.sops.yaml`.
Runner controller tokens belong to repository owner `funforgiven` and target
only `funforgiven/atollion`.

`https://cache.fahrican.com` serves Actions caches. Controllers derive the
repository, run, job and ref from Forgejo and give each job a short-lived
capability: pull requests read their own caches and the protected-main
baseline but cannot write the baseline or other pull requests' caches.
Controller credentials and signing keys never enter build containers.

## Backup and recovery

Compiler cache archives have a 64 GiB aggregate budget, with 16 GiB filesystem
headroom for uploads. The gateway evicts by least recent use and expires
archives unused for seven days or created more than 30 days ago. Maintenance
runs at startup and hourly even when no new uploads arrive. Active downloads
and recently accessed archives are protected by the gateway's lock
and reader tracking. Eviction causes a cold build; repository data and Actions
artifacts are stored separately. The 320 GiB cache PVC stays provisioned; its
thin `ceph-block` allocation is reclaimed by the node's weekly trim rather
than by shrinking the filesystem in place.
Compiler cache is disposable and excluded from application backups. Durable Git, LFS,
packages, Actions logs and artifacts use the separate Forgejo recovery path.

`forge-snapshot-backup` runs every six hours. The direct RBD CSI driver
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
exports through its default `.kopiaignore` support.
The 800 GiB backup volume provides staging and recovery headroom; its
provisioned size is not the amount uploaded to Backblaze. Do not shrink it in place.

`backup.py` serves recovery metrics. Its Velero `--once` hook checks that a
completed recovery source is less than eight hours old and never pauses the app.
The export controller has only namespace-scoped access to its Jobs, PVCs and
snapshots, plus read-only Velero backup status; the exporter has no Kubernetes
credential and no network access. A failed snapshot/export remains an alert,
while the application and earlier recovery archives stay available.

Velero copies the backup volume using Kopia. Because the global policy uses
`defaultVolumesToFsBackup: true`, the pod excludes `data,tmp`;
the opt-in `backup-volumes: backups` annotation alone does not protect the live
SQLite/Git volume from that global opt-out policy. Offsite retention is 30 days for daily and 90 days for weekly
backups. Recovery uses portable files and needs no CSI snapshot. Kopia
maintenance reclaims expired archive chunks in Backblaze. The restore verifier
accepts both quiesced `.tar.gz` and snapshot `.tar` manifests.

Forgejo's single-replica StatefulSet uses `OnDelete` updates: applying manifests
must not automatically restart agents' Git/API connections or running CI.
Apply application/image upgrades during a maintenance window. Do not delete
or roll the Forgejo pod during active work.

The monthly `backup-qualification/forge-restore-qualification` CronJob restores
the latest completed daily backup into fresh `forge-restore` volumes. Its
service account can delete only the two test PVCs and the test pod. It also has
PV get/patch permission for cleanup: the code checks the restore label, scratch
StorageClass, namespace and claim UID, then uses conditional JSON Patch before
releasing a volume. Velero restores the source PV's `Retain` policy even when
the scratch class specifies `Delete`, so the policy must be corrected after
verification. Successful drills remove their pod and both disposable volumes;
failed drills are kept for diagnosis. Completion is not reported until cleanup
finishes; controller logs and the Velero Restore record the result. Cilium
denies all ingress and egress in that namespace. Restore modifiers remove
production bootstrap and replace application containers with verification
processes; no duplicate Forgejo or OAuth callback runs during the test. The
controller allows four hours for offsite transfer and verification, with a
five-hour Kubernetes Job deadline for cleanup and shutdown. A 46 GB restore
takes about an hour; review timeout and bandwidth budgets as the data grows.

Velero 1.18 requires `persistentvolumes` in the resource inclusion list even
for filesystem restoration. `includeClusterResources: false` and the PVC
storage-class/volume-name modifiers still prevent source PV rebinding. Keep
Velero's injected `restore-wait` init container when changing modifiers.

The restore test requires:

- archive SHA-256 and SQLite integrity;
- an active ZITADEL provider;
- Git object integrity and `runner-qualification` `main`;
- successful Actions history and exact artifact bytes;
- the hashed Atollion import export, its issue/PR numbers and merge history,
  and the eight unfinished checkpoint files;
- distinct Atollion agent accounts, protected `main` and fast-forward-only merges;
- the recorded import commits as ancestors of restored `main`, and every
  imported PR commit.

Windows/macOS images are not backed up. When the archived GitLab manifests
under `/backups/legacy-gitlab*` are present, the verifier also checks their
sizes and checksums. A Velero `Completed` result alone is insufficient; both
verifiers must become ready.

For disaster recovery, suspend the `forge` Flux Kustomization, restore
the backup PVC, verify a completed archive, then extract its `data/` contents
onto an empty Forgejo data volume with UID/GID 1000. Reconcile the
SOPS runtime secrets and pinned image before starting Forgejo. Do not point
the isolated restore-test modifiers at production. Resume Flux only after
private HTTP/SSH, OIDC and repository/Actions checks pass.

## Monitoring

Prometheus scrapes authenticated Forgejo metrics and backup freshness.
Rules alert on application unavailability, stale or missing recovery archives,
failed Actions launchers, jobs waiting over 15 minutes, unavailable queue
metrics, failed restores, and no successful restore in 40 days.
Velero rules cover failed or overdue offsite backups.
Alerts use the cluster Alertmanager routing.

```sh
kubectl -n flux-system get kustomization forge
kubectl -n forge get pods,pvc,servicemonitor,prometheusrule
kubectl -n forge-ci get cronjob,jobs,pods
kubectl -n velero get backups,restores,podvolumebackups,podvolumerestores
kubectl -n backup-qualification get cronjob,job
kubectl -n forge-restore logs forgejo-0 -c database
kubectl -n forge-restore logs forgejo-0 -c git
```

## Archived GitLab export

The final GitLab object-store export is at
`/backups/legacy-gitlab-object-store/objects.tar.gz.sops.json` and is included
in daily and weekly Forgejo backups. Check its size and SHA-256 against the
adjacent `manifest.json` before use. Decrypt it with an administrator age
identity using `sops decrypt --input-type json --output-type binary`. The tar
archive contains `manifest.json` and `objects/<bucket>/<key>`; the inner
manifest records each object's size, SHA-256, ETag and content type. It includes
the last GitLab backup, `1788653718_2026_09_06_19.3.1-ee_gitlab_backup.tar`, and
its secrets. Keep decrypted material private.

Keep the objects under `services/hosts/gitlab/` in Backblaze until their
retention expires.

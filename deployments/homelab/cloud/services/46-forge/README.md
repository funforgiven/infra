# Private Forgejo and Actions

Forgejo runs in `services-v1`, with disposable Linux Actions jobs in `forge-ci`.
The private service is `https://git.fahrican.com`; Git SSH uses port `2222` on
the same services Gateway at `10.21.40.122`. Access is limited to the trusted
LAN, administration WireGuard network, and explicitly allowed service/runner
addresses. The shared Gateway preserves client IPs and uses Octavia health
monitors because its Service has `externalTrafficPolicy: Local`.

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
python3 components/cloud/services/forge/enroll.py --kubectl /path/to/undercloud-kubectl
python3 components/cloud/services/forge/enroll-runners.py
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
Git and standard build tools. Calico rules precede the provider's general
egress allow policy and deny metadata, cluster APIs, identity administration,
and other private networks. Each job has a two-hour limit and bounded CPU,
memory and ephemeral storage. The container registry credential can only read
packages and is held by kubelet, not mounted into job containers.

The qualification workflow in `components/cloud/services/forge/qualification.yaml`
checks private checkout, isolation, a Nix build, and artifact exchange between
two separate jobs. It runs weekly and retains its artifact for 45 days so
monthly recovery tests can verify real artifact bytes. Actions are pinned by
commit. These Forgejo jobs use the compatible artifact v3 protocol.

Build the Linux image with `nix build .#forge-linux-runner-image`, then publish
it with `components/cloud/services/forge/publish-runner-image.py`. Pin the
verified registry digest in `runners.yaml` before deployment.

The pinned upstream Runner 13.1.0 source also builds for Windows AMD64 and
macOS AMD64 without patches. Reproduce the builds with:

```sh
python3 components/cloud/services/forge/build-runners.py --work-directory /tmp/forge-runner-build
```

The emitted provenance records source/toolchain checksums and build flags.
Compilation is separate from native execution qualification: Windows 11 and
Quickemu macOS hosts must pass real workflows before receiving application
jobs. A job must receive only an ephemeral identity and a disposable guest
disk; reusable enrollment or cloud credentials must remain outside the guest.

### Native installation prerequisites

`native-inputs.json` pins the owner-supplied Windows 11 25H2 English x64 ISO,
VirtIO drivers, Apple recovery media and the upstream Apple signature verifier.
Run `verify-native-inputs.py --help` for the five local input paths. It checks
every SHA256 and exhausts the upstream chunklist verifier so the final Apple
RSA signature is checked as well as every image chunk. Installer verification
does not qualify the resulting VM or activate Windows.

Nova uses `host-model` on asiago for Windows 11 and taleggio for nested macOS,
with explicit Intel VMX on taleggio. Pecorino retains the default Westmere
baseline. The 32 GiB per-host reservation is unchanged. New/rebuilt guests on
the selected hosts require compatible migration destinations; do not assume
that host-model guests can move between Intel and AMD. Nested KVM is persisted
through the host role's `kernel` tag without unloading KVM or rebooting hosts.

The original OpenStack libvirt image lacks the TPM emulator. The Nix package
`libvirt-tpm-image` extends its exact deployed digest with the pinned `swtpm`
closure and a `tss` account matching Nova's UID/GID 42434. Its isolated test
qualified TPM 2.0 provisioning, certificates, initialization and shutdown as
that non-root identity. `compute-registry` can only read packages, is encrypted
for undercloud Flux, and is never mounted into a VM. Compute host addresses
are allowed only on the registry `/v2` route, without extending UI/admin access.

The initial libvirt image rollout uses `OnDelete` so one host can be qualified
before further restarts. OpenStack-Helm starts VM processes outside the pod
cgroup; still verify the existing guest PID/uptime and cluster health across
the first daemon restart. Enable Nova's TPM support only after libvirt reports
the emulator and TPM 2.0 in its domain capabilities.

## Backup and recovery

`backup.py` creates a native archive every six hours and before each Velero
backup. A supervisor stops Forgejo and its Git subprocesses, then acknowledges
quiescence. The backup checks SQLite integrity and captures the complete data
volume, including Git, LFS, packages, identity configuration, Actions logs and
artifacts. A checksum manifest is the completion marker. Seven local archives
are retained; an abandoned maintenance window automatically resumes the app.
These backups briefly interrupt HTTP/SSH access.

Velero copies only the backup volume, never the live SQLite/Git volume. Daily
offsite retention is 30 days; weekly retention is 90 days. The application and
backup PVCs use retained Cinder volumes and are excluded from Flux pruning.

The monthly `backup-qualification/forge-restore-qualification` CronJob restores
the latest completed daily backup into fresh `forge-restore` volumes. Its
service account can delete only the two test PVCs and the test pod. Calico
denies all ingress and egress in that namespace. Restore modifiers remove
production bootstrap and replace application containers with verification
processes; no duplicate Forgejo or OAuth callback runs during the test.

Velero 1.18 requires `persistentvolumes` in the resource inclusion list even
for filesystem restoration. `includeClusterResources: false` and the PVC
storage-class/volume-name modifiers still prevent source PV rebinding. Keep
Velero's injected `restore-wait` init container when changing modifiers.

Qualification requires archive SHA256, SQLite integrity, an active ZITADEL
provider, Git object integrity, the qualification branch, successful Actions
history and exact artifact bytes. If `legacy-gitlab.json` is present, it also
verifies the retained native GitLab backup and recovery secrets. A Velero
`Completed` result alone is insufficient; both verifiers must become ready.

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
kubectl -n flux-system get kustomization services-forge
kubectl -n forge get pods,pvc,servicemonitor,prometheusrule
kubectl -n forge-ci get cronjob,jobs,pods
kubectl -n velero get backups,restores,podvolumebackups,podvolumerestores
kubectl -n backup-qualification get cronjob,job
kubectl -n forge-restore logs forgejo-0 -c database
kubectl -n forge-restore logs forgejo-0 -c git
```

## Migration handoff

Atollion continues on GitHub while the destination and native runners are
qualified. Stage Git refs and GitHub metadata separately from its active
checkout. Do not transfer the managed `gh` credential into Forgejo; use the
repository-scoped CLI to export metadata and an offline migration dump.
The owner explicitly deferred migration: do not import Atollion or change its
workflows, remotes or active agent setup until separately instructed. Finish
infrastructure qualification and stop at migration readiness. The owner can
pause the active agent for the final catch-up once they request the cutover.

GitLab provisioning and cluster bootstrap are suspended, and its CAPI Cluster
is paused. Its three volume-backed VMs were gracefully shelved/offloaded after
offsite restore qualification, releasing 20 GiB of compute allocation. Their
attached disks remain a temporary rollback checkpoint during runner rollout;
final cloud/resource retirement is still separate from this staging step.
Keep the retained native GitLab recovery bundle until its declared retention
expires and the replacement has been accepted.

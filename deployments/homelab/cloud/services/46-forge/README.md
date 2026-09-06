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

The first libvirt daemon restart on asiago preserved the existing guest's
exact PID and uptime, kept all CAPI management nodes ready, and exposed TPM 2.0
emulation. Subsequent updates roll one daemon at a time. OpenStack-Helm starts
VM processes outside the pod cgroup; keep checking guest and cluster health
across image upgrades. Nova enables TPM scheduling on asiago and uses Barbican
for TPM secret storage. Other hosts do not advertise TPM scheduling yet.

### Native execution

Native jobs are launched by separate controllers in `forge-control`. Windows
uses a fresh Cinder disk and Windows 11 desktop VM for each job; the controller
waits for image conversion before asking Nova to boot. Cleanup verifies both
VM and disk deletion, including a disk whose preparation failed before any VM
existed. The controller refuses to delete foreign or attached preparation disks.

macOS uses the retained `forge-macos` NixOS host on taleggio. A forced SSH
command creates a QCOW2 overlay and private copies of the pinned firmware for
one guest, then deletes them after shutdown. The golden files stay root-owned
and read-only. The sealed guest has SIP, authenticated-root and AMFI enabled,
no builder administrator, and no SSH service. A fixed launch daemon mounts
only the read-only enrollment CD before login and starts the runner as
`forge-job`. The host console is loopback-only and accessible through the
operator SSH connection. Guest network traffic cannot use Slirp to reach host
services. Labels are `windows-x86_64` and `macos-x86_64`, with native `host`
execution; Windows runs in an unprivileged interactive desktop session.

Native qualification controllers poll the queue every minute. Fresh guests
have passed the platform workflow, artifact recovery, isolation and cleanup
checks, and the workflow repeats weekly. The qualification repository is
separate from Atollion and has its own scoped enrollment credentials. The Windows cloud credential is a CI-project member
and Barbican TPM-secret creator application credential (with implied reader);
its public expiry is recorded in `native-status.json`.
Rotate that record with the encrypted credential so expiry monitoring remains
accurate. Neither native guest receives the cloud credential or enrollment PAT.

## Backup and recovery

`backup.py` creates a native archive every six hours and before each Velero
backup. A supervisor stops Forgejo and its Git subprocesses, then acknowledges
quiescence. The backup checks SQLite integrity and captures the complete data
volume, including Git, LFS, packages, identity configuration, Actions logs and
artifacts. A checksum manifest is the completion marker. Seven local archives
are retained; an abandoned maintenance window automatically resumes the app.
These backups briefly interrupt HTTP/SSH access. The backup PVC is 800 GiB,
budgeted for seven archives plus the next archive, two native-image
generations and recovery headroom for the 80 GiB application volume. Review
this budget when expanding application storage or native images.

Velero copies only the backup volume, never the live SQLite/Git volume. Daily
offsite retention is 30 days; weekly retention is 90 days. The application and
backup PVCs use retained Cinder volumes and are excluded from Flux pruning.

The same backup PVC contains versioned native golden images and macOS
firmware. Acquire the Windows image from its private protected Glance record
and verify Glance's SHA-512; copy the macOS files through pinned operator SSH
and verify the golden manifest. Never back up an active writable job overlay.
Record the full signed source revision, creation/qualification Unix timestamps,
two distinct passing fresh-guest qualification run IDs, and each fixed file's
size and SHA-256 in a public backup manifest. `native_backup.py` documents and
validates the manifest fields and exact allowed files for each platform.

Publish a completed image set from restricted operator staging:

```sh
python3 deployments/homelab/cloud/services/46-forge/native_backup.py --publish \
  --kubectl /path/to/services-kubectl --source /restricted/staging/macos \
  --manifest /restricted/staging/macos-backup-manifest.json
```

Repeat for Windows. The utility checks the local files, refuses publication
during an active Velero backup, streams through authenticated Kubernetes exec,
checks the received bytes, and publishes the version index last. It preserves
previous completed versions and rejects interrupted or corrupt transfers.
After a newer offsite restore passes, retain the current and previous native
image generations locally; remove older unreferenced version directories
through operator access. Offsite retention remains unchanged. No
cloud or host credentials are installed in the backup pod. Keep at least 5 GiB
free and retain the previous qualified image until a new offsite restore passes.
Start a fresh Velero backup and isolated restore after every image publication;
a local copy alone is not an offsite recovery qualification.

The monthly `backup-qualification/forge-restore-qualification` CronJob restores
the latest completed daily backup into fresh `forge-restore` volumes. Its
service account can delete only the two test PVCs and the test pod. Calico
denies all ingress and egress in that namespace. Restore modifiers remove
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
history and exact artifact bytes. If `legacy-gitlab.json` is present, it also
verifies the retained native GitLab backup and recovery secrets. The retained
`legacy-gitlab-infrastructure` manifest additionally verifies the old backend
boot image and SOPS-encrypted cloud state checkpoints. The
`legacy-gitlab-object-store` manifest verifies the encrypted final export of
all remaining GitLab bucket objects, including the newest native backup.
Its retirement qualification separately restored, decrypted and checked every
object; the monthly verifier does not receive operator age keys. A Velero
`Completed` result alone is insufficient; both verifiers must become ready.
The database verifier also requires both native platform images, their public
provenance and qualification records, and all macOS firmware files to match
their restored SHA-256 manifests. Recover the macOS files root-owned/read-only
under `/var/lib/forge-golden/macos` on a host rebuilt from its pinned Nix image.
Reimport Windows as a private protected Glance image with the saved hardware
properties; update `windows.json` to its new ID before starting any controller.

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

The owner paused the Atollion agent and authorized migration on 2026-09-06.
The repository history is imported into private `funforgiven/atollion`.
Follow [ATOLLION-HANDOFF.md](ATOLLION-HANDOFF.md) for the import record,
separate agent identities, branch protection and remaining validation/cutover
sequence. The managed `gh` credential stays local; export uses the
repository-scoped CLI and an offline migration dump.
See [READINESS.md](READINESS.md) for the deployment and recovery evidence.
Atollion has two bounded Linux build slots with fresh 96 GiB disposable PVCs.
The native brokers retain separate enrollment tokens for Atollion and weekly
qualification, selecting the oldest waiting job across both repositories.
Application CI and recovery evidence must pass before resuming the paused agent.

The GitLab application and cluster have been retired. Retained recovery files
include its native backup, recovery secrets, backend boot image and encrypted
cloud state checkpoints, plus the final complete object-store export. The
dedicated project, network, GitLab flavors, image, load balancer, RGW service
and buckets have been deleted. The CI foundation retains the historical Terraform
controller name `gitlab-foundation` to preserve its existing state; that name
no longer provisions a GitLab service. Its source is
`components/cloud/services/forge/foundation-tofu` and its native flavor IDs are
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

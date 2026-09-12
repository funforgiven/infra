# Atollion migration record

The owner paused the Atollion agent and authorized migration on 2026-09-06.
The private destination is `https://git.fahrican.com/funforgiven/atollion`.
The offline import preserves GitHub main `6501d61d33a59bdc782f70e9e101f1a791050bad`,
59 issues, 57 pull requests and 10 labels. Issue/PR numbers, bodies, states,
creation timestamps, labels, PR head commits and merge commits were compared
with the final GitHub export. There were no tags, releases, comments or reviews.
GitHub remains a recovery source. Its managed credential was never sent to
Forgejo. The active checkout and its eight unfinished files have a separate
Git bundle, patch, file archive and SHA-256 checkpoint. Issue #116 stays open.

Combined migration PR #120 contains the CI and orchestration agents' signed
commits. Its reviewed head `0d71e0c699999359edd882af1d617ec24eaf7ce8`
passed all five required hosted checks in run 11 and merged through the
normal protected fast-forward path at 2026-09-07 23:02:34 UTC. All 31 incoming
commits were verified by Forgejo before merging; protected `main` points to
that exact head. It supersedes CI PR #119; both original authors remain in
Git history.
The real checkout cutover and live Forgejo audit completed at 2026-09-07
23:45 UTC after the fresh application restore and complete offsite backup
passed. The original development goal remains paused for the owner to resume.

## Destination and execution model

Forgejo is available at `https://git.fahrican.com` from the private LAN and
WireGuard. Git over SSH uses port 2222. Human access uses ZITADEL; keep the
encrypted local administrator credential for recovery. Each agent has
its own Forgejo identity and repository permissions. Each enrolled worktree
sets its own Git author, committer, signing key and SSH identity explicitly.

Actions execute in disposable environments with these labels:

| Label | Environment | Atollion execution |
| --- | --- | --- |
| `linux-x86_64` | Unprivileged Linux pod with Nix | Existing builds and checks; Windows cross compilation where supported by the project |
| `windows-x86_64` | Windows 11 Pro desktop VM, unprivileged interactive user | Run downloaded Windows artifacts and application tests; Direct3D software rendering is qualified separately from game compatibility |
| `macos-x86_64` | Intel macOS in Quickemu, unprivileged user, Nix and Apple command line tools | Native compilation and tests that do not require GPU acceleration |

The native brokers dispatch the oldest waiting job across explicitly enrolled
Atollion and qualification repositories, each with its own scoped PAT.
Guest jobs receive a one-job enrollment identity. OpenStack credentials
and the macOS host's restricted SSH key stay in the separate controller
namespace, outside repository job execution.

## Validated application changes

The migration PR adds `x86_64-darwin` alongside the existing `aarch64-darwin`
output, using application Nixpkgs revision
`a5cc6f2c37bf518436dc8d1c288ccd0c43c2f4c4`. Native application validation
uses this pinned environment and is recorded separately from infrastructure
toolchain qualification.

Windows execution exposed test fixture paths embedded from the Linux build
machine. The migration fixes all 15 affected loaders by embedding the same
718 fixture files in test binaries. The original parsers, assertions and corpus
bytes are preserved; detached binaries passed the affected tests when compiled
with deliberately nonexistent manifest-directory paths. Required Windows and
macOS CI also passed on the merged revision.

Keep checkout and artifact actions pinned to reviewed commits. Pass build
outputs between platforms as artifacts, and retain the application's actual
tests. Windows qualification verifies an interactive desktop and Direct3D 11
and 12 WARP; the game's renderer and runtime still require application-level
testing. The macOS runner has no GPU acceleration.

Translate GitHub-specific workflow settings and branch protection explicitly.
Review required checks, pull request approval rules, protected branches,
release permissions, packages and LFS. Enroll only repository-scoped agent
credentials. Credentials for infrastructure deployment are not application
build secrets. Do not grant untrusted pull requests access to release secrets
or allow privileged workflows to execute unreviewed pull request code.

## Completed local handoff

The canonical checkout is `/home/funforgiven/dev/atollion`, clean on protected
Forgejo `main` at `0d71e0c699999359edd882af1d617ec24eaf7ce8`, enrolled as
`atollion-coordinator`. Its `origin` uses Forgejo SSH. The former GitHub origin
is retained as `github` with pushes disabled; the GitLab remote is removed.

| Worktree | Account | Handoff state |
| --- | --- | --- |
| `/home/funforgiven/dev/atollion` | `atollion-coordinator` | Clean main; coordinates and merges |
| `/home/funforgiven/dev/atollion-worktrees/worker-1` | `atollion-worker-1` | `feat/116-logistics-frames`, all eight original unfinished files |
| `/home/funforgiven/dev/atollion-worktrees/worker-2` | `atollion-worker-2` | Detached at merged main, ready for assignment |
| `/home/funforgiven/dev/atollion-worktrees/worker-3` | `atollion-worker-3` | Detached at merged main, ready for assignment |

Every unfinished file was copied and checked against its original SHA-256,
mode and recovery archive before removing the redundant coordinator copy.
The live cutover audit verified the exact file set and modes again, along
with the merged PR, current review, all five PR checks, worktree identities
and remote configuration. Issue #116 remains open; its work was not committed
or discarded during migration.

The three migration agents were explicitly stopped before their old leases
were released and their old worktree authentication/signing disabled. Their
source branches and evidence are retained. The new Git common directory has
no existing worker leases. On resumption, the coordinator must spawn workers
waiting for assignment, bind each actual task ID to its distinct account,
worktree and owned paths, then assign work. Worker 1 receives the preserved
issue #116 work first.

The original goal attachment now contains the migration handoff and the full
checked-in `docs/AGENT_GOAL.md`. The existing goal row, paused status and usage
were preserved exactly. Resume that goal when ready; do not create a replacement
or reset its usage. The coordinator and workers must read the current
`AGENTS.md` and `docs/AGENT_ORCHESTRATION.md` before continuing.

Fresh application backup, isolated restore, complete offsite backup and normal
restore cleanup passed; names and checksums are in [READINESS.md](READINESS.md).

## Agent and merge policy

`atollion-coordinator` and `atollion-worker-1`, `atollion-worker-2`,
`atollion-worker-3` are distinct restricted, non-administrator accounts.
Each has an individual SSH signing/push key and a PAT restricted to Atollion.
SSH signing keys must also complete Forgejo's account-owned verification
challenge. Uploading a key permits authentication but does not by itself make
its commits verified. Check the nested `commit.verification` result from the
commit API before declaring a new agent ready for protected branches.
Encrypted recovery is in `host-runtime/atollion-agents.sops.yaml`; local
credentials are under `~/.local/state/atollion-forge/<account>/`, outside Git.
The coordinator leases one persistent agent and worktree per worker account.
These are separate Forgejo identities sharing an operator's Unix account;
they are not separate OS security boundaries.

Forgejo 15's native Actions web evidence routes require browser sessions;
repository PATs cannot authenticate them. Each account has its own secure,
mode-0600 `web-session.json`, bound to the enrolled username and user ID.
The application CLI sends these cookies only to fixed Atollion Actions evidence
routes and an explicit, source-checked retry route for a completed run. It
persists secure same-origin refreshes. API/review tokens
remain repository-scoped. Renew expired sessions from this repository's
development shell with `python3 components/cloud/services/forge/enroll-agent-sessions.py`.
The operator helper reads each password from SOPS into memory, verifies its
own login/settings/identity and artifact access, and writes no plaintext
passwords. Human ZITADEL sign-in is unchanged.

`atollion-branch-policy.json` records the applied main protection: no direct
pushes, signed commits, one independent whitelisted approval, dismissed stale
approvals and an up-to-date branch. Only the owner
and coordinator may merge. The policy applies to administrators too. The
September 12 operator migration enrolls local validation: required Actions
statuses are disabled and their contexts empty. The application's merge tool
verifies a receipt and logs bound to the exact head/tree, plus an independent
approval containing that receipt's SHA-256, and serializes protected merges
using the expected head SHA. The full native Actions matrix remains available
for manually scheduled certification. Forgejo's
same-repository workflow token has write permissions; the Actions bot is
excluded from both approval and merge whitelists.

`atollion-agent-policy.json` is the public enrollment snapshot installed at
`~/.local/state/atollion-forge/merge-policy.json` with mode 0600. The restore
verifier receives the same operator policy through `forge-restore-tools`.
It accepts local-mode protection only with this explicit enrollment and empty
contexts, retains all other safeguards, and continues to accept complete
historical Actions-mode protection in older recovery archives. Missing or
partial Actions protection never implies local mode. See
[the reviewed operator migration](https://git.fahrican.com/funforgiven/atollion/src/branch/ci/185-focused-local-validation/docs/LOCAL_VALIDATION.md#operator-migration).

Forgejo 15 checks instance merge-signing readiness even for fast-forward-only
merges. The instance has a dedicated SSH signing key, encrypted in
`signing.sops.yaml`, with fingerprint
`SHA256:GSzjKt3JxXg1yN3zTJ5RN/4m2ole2pK+cNBorJqBsf4`.
The initialization container installs it without replacing an existing key;
its private file is mode 0600 on the application volume and is included in
consistent application recovery archives. `MERGES = always` enables server signing
without requiring a second native MFA enrollment alongside ZITADEL.
Protected fast-forward merges still preserve the exact reviewed commit and
all enrolled approval, signature and validation requirements.

Linux application jobs have two concurrent slots, each with 2 requested CPUs,
a 3 CPU/6 GiB limit and a fresh 96 GiB Cinder scratch volume. A separate trusted
launcher creates jobs only when work is waiting. Its service account can list
and create jobs in `forge-ci` and read only the suspended Atollion template;
job containers have no Kubernetes token or reusable enrollment credential.
The template stays suspended; only the launcher copies its reconciled spec.
Generic ephemeral PVCs and their disks are deleted with completed job pods.
Do not back up disposable CI workspaces. Runner discovery tolerates temporary
maintenance failures with a shared 180-second budget for safe GET requests.
It retries transient connection errors and HTTP 502/503/504, while preserving
authentication, certificate and mutation failures. The committed bootstrap
script was verified in the future-job template on 2026-09-07 at 23:33 UTC.

Runner 13.1.0 can continue reporting after Forgejo revokes a cancelled job's
ephemeral identity. The Linux process supervisor recognizes that exact terminal
diagnostic and terminates its process group within a bounded grace period.
Native controllers check only their own registered runner; an enrollment absent
for 60 seconds releases its disposable environment. The macOS forced host
command writes a heartbeat to the SSH channel so a disconnected controller
reliably enters overlay cleanup even without a PTY. Keep the host's Nix system
configuration current when restoring its base image before enabling the broker.
These controller changes do not change Windows or macOS guest golden files.
The macOS host also waits up to 180 seconds for a preceding launcher's
exclusive cleanup lock. A flushed broker heartbeat precedes each acquisition
attempt, so a disconnected waiting controller exits before it can acquire
ownership. Seven focused tests cover contention, timeout and broken pipes.
Commit `9fd028d2c75978c75d335ecfb3283355f095a8e1` passed the cloud checks
and was activated at 17:52:12 UTC without changing the running guest PID.
The deployment proof is `/backups/native-lifecycle-20260906/host-lock-fix.json`.
The host subsequently received signed commit
`24d3a4d88a3e3850bfe6986e9695b9a631006e84` on 2026-09-07 at 18:20:58 UTC.
Its QEMU AppleSMC device implements indexed key reads and the precise
end-of-enumeration error expected by macOS. Nine actual QEMU device tests
passed in both the local build and the host's sandboxed build. The host built
content-addressed recipes with normal signature verification enabled.
That activation used system
`/nix/store/fagix6nvdaz6lc0v7dpxw1lcb2h79wm6-nixos-system-forge-macos-26.11.20260810.2fcb964`.
Activation held the native broker lock and verified an inactive guest,
absent disposable state and an unchanged golden manifest before and after
switching systems. The guest image, security settings and virtual CPU
configuration were unchanged.

The unchanged diagnostic workflow passed run 9, attempt 2 after activation.
The previously sustained PerfPowerService load of 85.7–100% was absent from
all 21 post-fix process samples; median sampled total guest CPU fell from
111.8% to 14.1%. All five small benchmark outputs matched, with no swap or
memory compression. These measurements establish the idle-load improvement;
the subsequent full application run 8, attempt 2 passed all five gates.
The final caching changes passed their separate current-head validation in
run 11, recorded below.

The dedicated macOS host now runs signed infrastructure revision
`07deb4bcbf45516003e18e54b066130ab4d687d8`, activated on 2026-09-07 at
20:31:33 UTC, with system
`/nix/store/6nm14sw045qbf9nnv2qlia4rn6c3gyy3-nixos-system-forge-macos-26.11.20260810.2fcb964`.
It retains the tested QEMU device fix, disables the unused DAMON memory
statistics sampler and accepts each job's optional cache capability on its
read-only enrollment media. Activation verified an idle runner and unchanged
golden files. No guest image rebuild was needed.

## Persistent build caches

`https://cache.fahrican.com` serves Actions caches through the private reverse
proxy. Its isolated `forge-cache` namespace holds a 320 GiB Cinder volume,
with a 240 GiB cache quota and 16 GiB reserved free-space floor. Entries expire
after seven days without access or thirty days total. These reproducible
build outputs are excluded from backups. Prometheus alerts cover unavailable
replicas and low disk space; runner logs identify cache fallback explicitly.

All three compilation lanes cache Cargo downloads and debug/release outputs:
Linux quality, Windows cross compilation on Linux, and native Intel macOS.
Windows 11 executes the resulting Windows test bundles. Cache keys include
the actual compiler, target, pinned manifests and build flags. Compatible
source revisions may reuse dependencies; every required validation still runs.
A cache outage falls back to a complete cold build.

The initial populated-cache comparison used PR #120 head
`bcb72161a1a4c5ddefba467b47c0daf276229140`, workflow run 10. Its cold
attempt passed every required check and saved all nine cache parts. In the
second attempt, Windows compilation restored all three parts (1.68 GiB
compressed): the build job fell from 18m24s to 6m04s and its two domain
Cargo commands fell from 11m49s to 2m49s combined. Native macOS restored
all three parts too; its job fell from 30m46s to 16m22s, with the two
Cargo commands falling from 13m56s to 3m05s. These job durations exclude
waiting for runner allocation. Native tests and provisioning still dominate
the remaining time; they are not cached or skipped.

Linux's second attempt missed because its key included a disposable Nix
workspace rpath. The owner requested stopping that cold rebuild. Only that
Linux job was stopped; the populated caches and other jobs were preserved.
The second attempt therefore does not qualify as a successful full matrix.
Commit `0d71e0c699999359edd882af1d617ec24eaf7ce8` normalizes only that
disposable Linux rpath in the cache fingerprint, retaining the raw compiler
flags as evidence. An exact, input-bound compatibility key recovers the
original Linux archives. Run 11 restored all nine existing cache parts;
Linux Clippy fell from about 164 seconds cold to 12 seconds with reuse.
Compatible prefix restores are successful reuse even when the action's
`cache-hit` output is false, which indicates a non-exact key match.

That commit uses three Cargo build workers within the existing CPU limits.
Windows and macOS execute two independent native test binaries concurrently;
each binary retains one test thread, the original assertions, source and
binary checks, and bounded deadlines. Local invocation remains serial by
default. Cancellation terminates and reaps the owned process groups.
Focused process-cancellation tests, all 202 Python tests, 26 CI contracts and
the pinned workflow checker passed before the signed push. Run 11 then
passed all five current-head checks with the independent approval still
current. Its artifacts confirm all nine compatible cache restores, refreshed
target archives and complete source-bound validation.

| Job | Initial cold run | Cached run with three build workers and parallel native binaries |
| --- | --- | --- |
| Linux quality | 34m24s | 19m32s |
| Windows cross build | 18m24s | 8m43s |
| Windows 11 native validation | 10m20s | 6m26s |
| Intel macOS build and validation | 30m46s | 14m33s |

These job durations exclude allocation waits. The newer revision republishes
target archives, unlike the earlier exact-key rerun. Windows provisioning
added 5m24s between its producer and native job. The native test phase itself
fell from 475.522 to 251.099 seconds on Windows and from 571.093 to
325.416 seconds on macOS. All 22 native executables ran, with 475 tests per
profile on Windows and 476 per profile on macOS. Linux retained 485 workspace
tests, 476 release-domain tests, 202 Python tests and 26 CI contracts.

The subsequent Linux runner image `13.1.0-gzip.1`, digest
`sha256:b0d2adcb64e13b15ecdd2b7c89830c827f4e2112b54aa1b8e45f964cf643e74f`,
uses three-worker fast parallel gzip for Actions archives. The measured
Windows save bottleneck was 193 seconds constructing archives and 13 seconds
uploading them. GNU tar resolves the reviewed wrapper through `PATH`;
bidirectional old/new archive CRC and file-hash checks passed. The cache
format and version remain unchanged, so old archives remain usable. Faster
compression can produce larger archives, still subject to the existing
quota and retention bounds. The macOS BSD tar path is unchanged. Protected-main
run 12 used the new image for both Linux compiler jobs. Its Windows target
archive construction took 62.780 seconds, versus 193.027 seconds in run 11;
publication took 11.403 seconds. Archive sizes differ, so this is an observed
production comparison rather than a controlled benchmark.

Protected-main run 12 also passed all five checks on the merged revision,
finishing at 2026-09-07 23:40:21 UTC. All nine Cargo download/debug/release
cache parts were saved to the trusted-main namespace, so new PRs have a
populated baseline. This first main-branch seed rebuilt in its separate trust
scope; PR-produced archives were preserved in their original scopes.

The current cache action is pinned Forgejo `actions/cache`, with separate
Cargo download, debug and release archives. Existing populated archives are
preserved. A new source revision can reuse dependencies and then publishes
updated build archives; this upload cost is absent on an exact-key rerun.
Cache reuse accelerates compilation, but runner provisioning and actual
test execution still contribute to the complete workflow duration. A
five-minute complete matrix has not been established.

Trusted controllers derive repository, run, job, attempt, head and ref from
Forgejo metadata and grant only a short-lived capability to the assigned job.
Pull requests can read their own caches and the protected-main baseline,
but cannot write the baseline or another pull request's caches. Main pushes
run the full matrix to populate that trusted baseline. Controller credentials
and the backend signing key never enter build containers or guests. The
private proxy omits request paths and queries from access logs, and workflow
setup masks each capability before the cache action logs its resource URL.

Windows cancellation qualification run 14 and macOS run 13 both verified
automatic cleanup on 2026-09-06. The complete proofs are retained on the
backup volume under `/backups/native-lifecycle-20260906/`; application CI
and application restore qualification remain separate checks.

Forgejo 15 requires repository ownership for runner management, including
queue reads; a collaborator's admin role is insufficient. Atollion controller
tokens therefore belong to repository owner `funforgiven` and explicitly
target only `funforgiven/atollion`. The queue launcher has `read:repository`;
the isolated registration/native controllers have `write:repository`.
These credentials never enter agent worktrees or execution containers.
The unnecessary `forge-runner` application collaborator and its unusable
Atollion controller tokens were removed; qualification credentials remain
owned by `forge-runner` for its own qualification repository.

Quickemu provides Intel macOS validation. The GDD's ARM64 macOS certification
and physical GPU/calibrated performance requirements remain explicit separate
evidence; Intel software-rendered CI does not establish those results.

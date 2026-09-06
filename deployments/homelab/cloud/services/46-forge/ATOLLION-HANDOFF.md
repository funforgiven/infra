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
commits and is undergoing real hosted validation. It supersedes CI PR #119
after a successful protected merge; both original authors remain in Git history.
The active checkout must remain paused until validation, remote cutover and
application backup/restore verification finish. This migration record does
not claim that the application qualification has already passed.

## Destination and execution model

Forgejo is available at `https://git.fahrican.com` from the private LAN and
WireGuard. Git over SSH uses port 2222. Human access uses ZITADEL; keep the
encrypted local administrator credential for recovery. Each agent should have
its own Forgejo identity and repository permissions. Git author and committer
fields remain independent of the account authenticating a push, so configure
each agent's commit name and email explicitly when moving it.

Actions execute in disposable environments with these labels:

| Label | Environment | Intended Atollion work after cutover |
| --- | --- | --- |
| `linux-x86_64` | Unprivileged Linux pod with Nix | Existing builds and checks; Windows cross compilation where supported by the project |
| `windows-x86_64` | Windows 11 Pro desktop VM, unprivileged interactive user | Run downloaded Windows artifacts and application tests; Direct3D software rendering is qualified separately from game compatibility |
| `macos-x86_64` | Intel macOS in Quickemu, unprivileged user, Nix and Apple command line tools | Native compilation and tests that do not require GPU acceleration |

The native brokers dispatch the oldest waiting job across explicitly enrolled
Atollion and qualification repositories, each with its own scoped PAT.
Guest jobs receive a one-job enrollment identity. OpenStack credentials
and the macOS host's restricted SSH key stay in the separate controller
namespace, outside repository job execution.

## Application changes to review at cutover

The last inspected Atollion flake exposes `aarch64-darwin`, but the available
macOS guest is `x86_64-darwin`. Reinspect the current flake when migration is
authorized: the GitHub agent may have changed it in the meantime. Add the
Intel Darwin output and confirm its dependency support in the application
repository at that point. The native infrastructure qualification uses
Nixpkgs revision `6713828a351efa628b025a1adf7f43cbf8597513`; this verifies the
Intel guest toolchain and does not establish application compatibility.

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

## Authorized cutover sequence

The owner has authorized this sequence:

1. Coordinate the final pause with the active Atollion agent. Record the
   current GitHub refs and inspect uncommitted work without discarding it.
2. Export the current Git refs, tags, LFS objects and relevant GitHub metadata
   through the repository-scoped access already available. Previous exports
   are staging material and cannot be assumed current.
3. Import into a private Forgejo repository and compare branch and tag object
   IDs, LFS availability and the exported metadata. Review access, protections
   and agent identities before changing the active checkout.
4. Add the application workflows and platform adjustments, then enroll its
   repository-scoped runners. Run the actual Linux, Windows and macOS checks
   and verify artifact transfer before treating those platforms as supported.
5. Switch the active checkout and agent integration to the verified Forgejo
   destination. Confirm fetch, push and pull request behavior while preserving
   unfinished files. Preserve the GitHub source and cutover record for recovery.
6. Take a new backup containing the application and verify restoration of its
   repository and LFS data. Record the result with the existing restore
   qualification evidence. Only then hand the paused goal back for continuation.

## Agent and merge policy

`atollion-coordinator` and `atollion-worker-1`, `atollion-worker-2`,
`atollion-worker-3` are distinct restricted, non-administrator accounts.
Each has an individual SSH signing/push key and a PAT restricted to Atollion.
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
approvals, all five named PR checks and an up-to-date branch. Only the owner
and coordinator may merge. The policy applies to administrators too. The
application's merge tool additionally verifies current-head actual Actions
runs/tasks and serializes merges using the expected head SHA. Forgejo's
same-repository workflow token has write permissions; the Actions bot is
excluded from both approval and merge whitelists.

Linux application jobs have two concurrent slots, each with 2 requested CPUs,
a 3 CPU/6 GiB limit and a fresh 96 GiB Cinder scratch volume. A separate trusted
launcher creates jobs only when work is waiting. Its service account can list
and create jobs in `forge-ci` and read only the suspended Atollion template;
job containers have no Kubernetes token or reusable enrollment credential.
The template stays suspended; only the launcher copies its reconciled spec.
Generic ephemeral PVCs and their disks are deleted with completed job pods.
Do not back up disposable CI workspaces.

Runner 13.1.0 can continue reporting after Forgejo revokes a cancelled job's
ephemeral identity. The Linux process supervisor recognizes that exact terminal
diagnostic and terminates its process group within a bounded grace period.
Native controllers check only their own registered runner; an enrollment absent
for 60 seconds releases its disposable environment. The macOS forced host
command writes a heartbeat to the SSH channel so a disconnected controller
reliably enters overlay cleanup even without a PTY. Keep the host's Nix system
configuration current when restoring its base image before enabling the broker.
These controller changes do not change Windows or macOS guest golden files.

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

# Atollion migration boundary

The owner has explicitly postponed migration. Atollion's active repository is
`git@github.com:funforgiven/atollion.git`; its working checkout and the agent
using it stay on GitHub until the owner instructs the cutover. Infrastructure
qualification uses only `forge-runner/runner-qualification` on Forgejo.
Do not import an application repository, change its remotes or workflows, or
redirect an agent as part of infrastructure readiness work.

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

The native brokers remain scoped to the qualification repository during this
hold. Guest jobs receive a one-job enrollment identity. OpenStack credentials
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

Run this sequence only after the owner requests migration:

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
   destination. Confirm fetch, push and pull request behavior and resume the
   agent. Preserve the GitHub source and the cutover record for recovery.
6. Take a new backup containing the application and verify restoration of its
   repository and LFS data. Record the result with the existing restore
   qualification evidence.

Until that instruction arrives, complete infrastructure work and stop at this
boundary. Nothing in this document authorizes an Atollion import or cutover.

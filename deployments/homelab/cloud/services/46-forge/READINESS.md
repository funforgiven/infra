# Forgejo readiness and retirement record

The owner authorized Atollion migration after pausing its agent on 2026-09-06.
Its GitHub history is imported and checked; application workflows and agent
orchestration are in PRs #119 and #120. The paused checkout's unfinished files
are checkpointed and remain intact. Follow [ATOLLION-HANDOFF.md](ATOLLION-HANDOFF.md)
for application validation and cutover progress. The completed native results
below remain infrastructure qualification evidence.

## Deployed service

- Forgejo 15.0.7 runs in the existing services Kubernetes cluster.
- Private HTTPS is `https://git.fahrican.com`; Git SSH uses port 2222.
- Access is through the private LAN and WireGuard. Human sign-in uses ZITADEL;
  its MFA policy remains authoritative. The human account is active and is not
  an instance administrator. Recovery administration uses an encrypted local
  credential; automation has a separate non-administrator identity.
- Linux Actions use disposable unprivileged Kubernetes pods. Native controller
  credentials stay in `forge-control`, outside repository execution.
- Native polling runs every minute with separate Atollion and qualification tokens.
  Its native platform qualification workflow runs weekly.

## Native qualification

Full workflow runs 8 and 9 each passed Windows, macOS, and both independent
Linux artifact-recovery jobs. Controller logs confirmed Windows VM/root-disk
removal and macOS overlay, enrollment-media and mutable-firmware removal.

| Platform | Qualified behavior | Retained recovery source |
| --- | --- | --- |
| Linux x86_64 | Nix build, repository operations, artifact upload and recovery | Pinned runner image and repository configuration |
| Windows x86_64 | Windows 11 Pro 25H2, unprivileged interactive desktop, immutable trusted tools, private-network isolation, Direct3D 11/12 WARP | Private protected Glance image `e8f8b4f6-3956-44fe-80cc-1bd99bde08be` |
| macOS x86_64 | macOS 15.7.9, Nix and Clang native build, SIP/authenticated-root/AMFI, non-administrator job identity, host/private-network isolation | Root-owned read-only Quickemu golden files on `forge-macos`, mirrored in the backup set |

The macOS runner has no GPU acceleration. These infrastructure results do not
establish Atollion game compatibility; review its current Intel Darwin flake
outputs and run its real platform tests when migration is authorized.

## Backup evidence

Quiesced application archives run every six hours, with seven local copies.
The 800 GiB backup volume budgets archive rotation and native-image recovery
without changing the configured 80 GiB application volume.
Encrypted offsite copies retain daily backups for 30 days and weekly backups
for 90 days. Monthly recovery qualification runs in a namespace with all
network ingress and egress denied; test volumes are dynamically provisioned
and cannot bind production volumes.

The complete offsite backup `forge-native-complete-20260906082922` finished at
2026-09-06 08:49:28 UTC. It contains the application archives, both qualified
native images and macOS firmware, the retained native GitLab recovery bundle,
its old backend boot image, and SOPS-encrypted cloud-state checkpoints.

The corresponding isolated restore is `forge-qualification-20260906085053`.
The transfer completed at 2026-09-06 09:45:53 UTC and the qualification job
passed at 09:49:04 UTC. Both database and Git verifiers became ready. The
restored pod had no service-account token or production volume bindings;
independent TCP probes confirmed that it could not reach Forgejo, ZITADEL
or the Kubernetes API.

Before deleting RGW, all 45 remaining objects across its 13 buckets were
retained in a SOPS-encrypted export. This includes the newer native GitLab
backup `1788653718_2026_09_06_19.3.1-ee_gitlab_backup.tar` and its matching
recovery secrets. The objects total 16,754,444 bytes. Supplementary offsite
backup `forge-gitlab-objects-20260906101606` and isolated restore
`forge-gitlab-objects-20260906101606-check` completed successfully. At
10:17:18 UTC, the independently restored export was decrypted and every
object's size and SHA-256 verified. Production network access was denied.
The encrypted file's SHA-256 is
`34b75bbeabddee700d2df05738129201e819eac3e7a3c80042f4e48914f754f3`.
The supplementary backup retains 90 days of recovery history, and the
canonical copy is on the Forgejo backup volume for subsequent scheduled backups.

Native image backup manifests retain SHA-256 file hashes, signed source
revisions and two independent passing qualification run IDs. Windows uses
runs 8 and 9; the macOS image was first qualified by runs 5 and 6 and passed
again in full runs 8 and 9.

## Retirement and validation

GitLab's application and dedicated Kubernetes cluster are deleted. Its DNS,
ZITADEL application, Resend sending key, WireGuard rules, obsolete bootstrap
credentials and controller RBAC have been removed. The final project, image
and object store have also been deleted following the owner's explicit
cleanup approval and the successful restores above. Fresh API checks confirmed
that the old project, network, router, backend image and three GitLab flavors
are absent. The GitLab RGW deployments, user, 13 buckets and dedicated pools
are gone; unrelated Ceph pools were preserved.

Obsolete Windows preparation volumes, snapshot and unattended installer were
deleted; the owner's original ISO and the qualified protected Windows image
remain. Obsolete macOS debug and preparation trees were removed only after
rechecking the immutable golden files. The CI project, existing native flavor
IDs, active macOS host and its protected Nix recovery image remain intact.

The historical Terraform controller name `gitlab-foundation` is retained to
preserve the existing CI state. Its source now lives under the Forge
component. Explicit moves preserve the native flavor IDs, and the CI project
has `prevent_destroy` protection.

No GitLab-specific Backblaze writer credential was enrolled in the credential
store. Its unused writer declaration has been removed; existing backup
retention rules and encrypted historical recovery material remain.

Cloud configuration and Kustomize checks passed, including the existing native
broker and image-backup integrity tests. All 43 service credential and runtime
contract tests passed. Commits use the repository's signed conventional commit
workflow. Unrelated workstation configuration edits were preserved.

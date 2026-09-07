# Forgejo readiness and retirement record

The owner authorized Atollion migration after pausing its agent on 2026-09-06.
Its GitHub history is imported and checked. Application workflows and agent
orchestration passed all five required checks and merged in protected PR #120
at 2026-09-07 23:02:34 UTC, preserving the exact reviewed head
`0d71e0c699999359edd882af1d617ec24eaf7ce8`. Protected-main run 12 also passed
all five checks and published all nine trusted compiler cache parts. The real
checkout and goal handoff completed and passed its live audit at 23:45 UTC;
all eight unfinished files are preserved in worker 1. The original goal remains
paused. [ATOLLION-HANDOFF.md](ATOLLION-HANDOFF.md) records worktree identities,
merge rules, validation results and measured cache performance.

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
- Persistent compiler caches use private `https://cache.fahrican.com` and a
  separate 320 GiB volume. Trusted controllers grant capabilities scoped to
  the actual repository, job and attempt; pull requests cannot write the
  protected-main cache baseline. The service alerts on unavailable replicas
  and low free space. Disposable builds remain complete when caching is unavailable.

## Native qualification

Full workflow runs 8 and 9 each passed Windows, macOS, and both independent
Linux artifact-recovery jobs. Controller logs confirmed Windows VM/root-disk
removal and macOS overlay, enrollment-media and mutable-firmware removal.

| Platform | Qualified behavior | Retained recovery source |
| --- | --- | --- |
| Linux x86_64 | Nix build, repository operations, artifact upload and recovery | Pinned runner image and repository configuration |
| Windows x86_64 | Windows 11 Pro 25H2, unprivileged interactive desktop, immutable trusted tools, private-network isolation, Direct3D 11/12 WARP | Private protected Glance image `e8f8b4f6-3956-44fe-80cc-1bd99bde08be` |
| macOS x86_64 | macOS 15.7.9, Nix and Clang native build, SIP/authenticated-root/AMFI, non-administrator job identity, host/private-network isolation | Root-owned read-only Quickemu golden files on `forge-macos`, mirrored in the backup set |

The macOS runner has no GPU acceleration. Atollion's separate application
checks passed in migration PR #120; these results do not establish physical
GPU behavior or ARM64 macOS certification.

Dedicated cancellation qualifications also passed on 2026-09-06. Windows run
14 was canceled at 16:42:15 UTC; the controller verified deletion of its owned
VM and attached disks at 16:43:39. macOS run 13 was canceled at 16:56:44;
its controller completed at 16:57:47, with QEMU inactive and the writable
overlay absent. Both checks bound the actual running task to its controller
and used no manual controller or guest cleanup. Their complete proofs are
retained under `/backups/native-lifecycle-20260906/` for offsite backup.

## Backup evidence

Quiesced application archives run every six hours, with seven local copies.
The 800 GiB backup volume budgets archive rotation and native-image recovery
without changing the configured 80 GiB application volume.
Encrypted offsite copies retain daily backups for 30 days and weekly backups
for 90 days. Monthly recovery qualification runs in a namespace with all
network ingress and egress denied; test volumes are dynamically provisioned
and cannot bind production volumes.

The post-merge Atollion archive
`forgejo-20260907T230308Z-a81f2c3e.tar.gz` is 2,029,026,764 bytes, SHA-256
`2b8c8021975f7f12532b2039001f0e3a1a456163b0d9946496ed805ba61622fa`.
Its isolated backup `forge-atollion-application-20260907230539` and restore
`forge-atollion-application-20260907230539-check` completed successfully.
Qualification passed at 2026-09-07 23:19:23 UTC: database and Git checks,
all 11 migration manifest files, all eight original unfinished files, three
separate recovery volumes, no service-account token, and denied ingress and
egress. Actual TCP probes confirmed private Forgejo and API access was blocked.
The restore proof is retained at `/backups/atollion-migration/restore-proof.json`.
Both isolated namespaces, their three temporary volumes and the restore
modifier were subsequently removed through normal UID-guarded deletion.
Production storage and the completed backup/restore records were preserved.

The fresh complete backup `forge-atollion-complete-20260907232101` finished
at 2026-09-07 23:29:23 UTC with 53,491,574,375 bytes and 90-day retention.
Its filesystem snapshot is `2e61fa485e19fa2981f8d57a75a36c69`. It includes the
post-merge application archive, migration evidence and unchanged native
recovery images. Disposable compiler caches are excluded from backups.

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

Cloud Python, YAML and Kustomize checks passed for the infrastructure changes.
Focused tests also covered cache isolation and archive compatibility, native
process supervision, signing-key persistence and maintenance recovery. The
application's complete required matrix passed on both the reviewed PR and
protected main. Commits use the repository's signed conventional commit
workflow. Unrelated workstation configuration edits were preserved.

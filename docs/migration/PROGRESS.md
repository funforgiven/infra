# Migration status

This journal preserves the preparation and early execution record. The live
migration and independent recovery checks are complete; see
[LIVE-RECOVERY.md](LIVE-RECOVERY.md) for current results. The active GitOps
source now follows signed `main` commits. Statements below about work that had
not yet run describe the earlier audit stage.

Preparation is complete. The owner has now requested a sequential live migration, conditional on verified recovery copies. The recovery audit has started; no physical host has been rebooted, reinstalled or reformatted.

Worktree: `/home/funforgiven/dev/infra-nixos-kubernetes`.
Branch: `codex/nixos-kubernetes-migration`, based on `8d5f130`.
The preparation did not change main's tracked files. The current execution
audit has created and removed isolated restore copies and has written new
encrypted recovery objects to Backblaze. It has made no production deployment,
provider apply, server installation or disk reformat. PiKVM console identity and
keyboard control have been qualified without boot-media or power changes; Beets
writers are paused for an independent cold-volume backup pilot. Read-only
inspection captured hardware, Kubernetes/cloud volumes, addresses, certificate
fingerprints, provider states, runtime credentials and SSH host identities;
private recovery values are kept encrypted or in owner-private scratch space.

Implemented: three NixOS/K3s servers with mirrored-SATA disko, networking,
SSH/SOPS bootstrap and off-server etcd backups; Cilium 1.20.2 with eBPF kube-proxy replacement, MetalLB, Multus and direct Rook-Ceph RBD/CephFS; one
semantic Flux graph and a restore suspension overlay; retained apps and
independent AWS mail/providers; supported UniFi KubeVirt guest; original OIDC
identities, TLS/ACME/runtime keys and encrypted provider state archives;
native database recovery and preserved HA IoT/pairing state. Removed active
OpenStack/CAPI/Magnum and native Windows/macOS runner deployments.

Inventory: all 798 source document entries, 74 old Flux stages, 24 provider
files, 23 explicit source claims, 56 captured live claims and 74 PVs are mapped.
Cloud inspection also mapped 65 Cinder volumes, 11 Nova guests and 17 Glance
images; captured the single Manila share and 13 floating IPs. Each floating IP
is now joined to its actual Neutron/Octavia owner with an explicit disposition;
the actual guest workload Kubernetes API is .40.197, and the retained public
HTTPS/STUN addresses are .40.128/.40.129. All 54 captured certificate/account/
provider objects have explicit ownership actions in certificate-plan.json. Forty-one TLS
Secrets, twelve provider state Secrets and one ACME account key are archived
as ciphertext. Byte exports and used-byte/capacity measurements are future
execution gates, not completed preparation work.

Validation: all five NixOS hosts and the three server disko selections evaluate;
flake checking with `--no-build --all-systems` passes. The combined homelab Nix
check builds successfully, including 280 retained network/service/recovery tests,
manifest checks, provider formatting, RouterOS syntax and shell checks. Full
schema validation passes for 33 Kustomize entrypoints, 29 Flux stages and 464
exact pinned Helm-rendered resources, with no failures or missing schemas.
All four provider configurations passed offline init/validate; four encrypted
state exports verified lineage, mode and overwrite protection. Credential
enrollment passed 46 tests again. All 106 generated claim/guest transfer
resources pass strict schemas, and the actual four retained TLS/account Secrets
pass offline key/fingerprint/hostname checks and private export safeguards.

Added DATA-MIGRATION.md and RUNBOOK.md with future writer freeze, independent
export/restore, native DB/UniFi/IoT recovery, SATA installation, CNI-before-Flux
bootstrap, initial Ceph reuse hold, staged release, external provider/mail
coordination, backup qualification and explicit rollback boundaries. One-time
gateway TLS seeding avoids Flux overwriting renewed certificates. Matrix's
managed pg_hba rules now use the target pod CIDR and preserve custom/local rules.
Helm values-schema references are pinned/localized into a derived public cache;
the full render/schema check succeeds without network access or skipped schemas.

The current operation cleanup removes obsolete guest/cloud API permissions
and target VLANs 31/32/33, with a separate exact-identity retirement phase that
requires verified independent exports. All eight retained OIDC client outputs
have an encrypted refresh path. All twelve provider states have explicit
ownership dispositions; the four retained exports match the newer capture.
Matrix/AudioMuse database-only bootstrap exports passed strict schemas on their
actual private inputs: eleven resources, mode 0600 and overwrite refusal, without
cluster calls. Current service/network/IoT docs describe the physical target;
dated Forgejo records are clearly marked as source recovery evidence.

Found and fixed two target dependency gaps: Linux Actions required retired CAPI
worker labels, and Forgejo snapshots lacked the independent snapshot controller.
NixOS now declares physical CI eligibility; required job anti-affinity spans
physical hostnames. The Rook stage installs three v1 snapshot CRDs and the pinned
controller, and enables RBD CSI snapshots. Validation rejects missing snapshot
dependencies and stale CAPI scheduling constraints. MetalLB now uses verified
v0.16.1 release bytes with immutable controller/speaker image digests. All vendor
sources/hashes and twelve chart archives are recorded; local vendor hashes are
checked by both refresh and offline validation.

Latest broad checks: full formatting passed; all-system flake evaluation and
all five host/four exported disko configurations evaluate; the combined Nix
check built successfully with 273 tests. Full offline schema validation passed
33 entrypoints, 29 Flux stages, 1,194 validation instances and 443 Helm resources,
with zero failures/missing schemas. Working-tree and 851-commit history secret
scans found no leaks. At that preparation checkpoint, main was clean at
8d5f130 and no live changes had occurred.

Repeatable source capture is implemented and qualified through the frozen source
flake. It read 742 Secrets/ConfigMaps into ciphertext, the existing 56 claims/74
PVs and complete cloud/actual owner inventories. All nine artifact hashes and
owner-only modes verified; four fresh provider states and four TLS seed resources
remain compatible with the reviewed prepared inputs. Manila export enumeration
uses the required 2.9 microversion. Capture cannot overwrite or automatically
update prepared Git inputs and publishes its complete manifest last.

The residual documentation/reference audit is complete: current Matrix/backup/
credential guides describe the physical target, dated Matrix evidence is separate,
host-only credentials are consolidated and all mapped target paths exist. Final
broad verification passed: 273 combined tests, 46 enrollment tests, all-system
flake/five host/four disko evaluation, four provider validations, full offline
schemas/Helm and redacted working-tree/history secret scan. The migration branch
is committed locally for review; no push or merge occurred. See
[ACCEPTANCE.md](ACCEPTANCE.md) for the original requirement-by-requirement audit.
Hardware boot, mirrored-disk boot, network/USB behavior, independent backup
completeness, actual byte exports/restores and PiKVM control remain future live
execution qualifications. No live changes occurred.


## Execution recovery audit — 2026-10-12

The owner selected Backblaze for durable exports, with download and restore
verification on the workstation. The primary recovery procedure builds fresh
application storage and restores data/configuration into it; old cluster etcd
state is fallback evidence. Retain claim names, namespace mappings, numeric
ownership, mount paths/subpaths, native database roles and stable application
identities. Source Cinder/Manila bindings never become direct Ceph bindings.

PiKVM ricotta at 10.21.90.3 is authenticated through pinned SSH and an encrypted
SSH tunnel to the local API. It is the existing v2 unit, connected to pecorino;
the console marker and source host identity agree. A harmless Shift key press
and release verified USB keyboard control. No switch is present at this device;
virtual installer-media boot and physical disk identity remain installation gates.

Verified recovery evidence is recorded in the owner-private workstation folder
`/tmp/homelab-migration-audit-20261012`. It includes exact B2 object versions and
hashes, restored snapshot IDs and a per-source application recovery ledger.
The ledger remains `cutoverReady: false`. The ledger and verification receipts
are also preserved as an encrypted B2 checkpoint under
`services/kubernetes/plugins/migration/20261012/`; its exact object version was
downloaded, authenticated and checked against every artifact hash.

- Undercloud and management encrypted etcd backups downloaded, authenticated,
  and restored with native etcdutl; the OpenStack authoritative archive passed
  its inner hashes and archive-read checks. This does not qualify a whole-cloud
  restore or copy any application volume bytes.
- Home Assistant and Thread recovery archives from today's Kopia backup
  downloaded directly onto the workstation and passed their native offline
  verifiers, including JSON/SQLite integrity and Thread dataset structure.
- Both Matrix databases restored locally using PostgreSQL 17 from today's B2
  dumps. Relay queue/media presence, bot identity and the encrypted crypto
  recovery canary passed the existing offline verifier.
- AudioMuse's dump PVC was absent from today's filesystem backup because only
  a completed backup Job mounted it. A fresh online PostgreSQL 15 native dump
  is now encrypted in B2, downloaded/decrypted and restored: 29 application
  tables and expected role ownership passed. This is a verified online recovery
  point, not the final quiesced cutover export.
- Today's UniFi and AWS mail Restic payloads downloaded and passed restored-file
  verification. The UniFi archive also passed archive readability checks; its
  cold guest disk export and isolated guest boot remain pending.
- A fresh source capture preserves 745 Secrets/ConfigMaps, 54 certificate/state
  objects and current controller/volume/cloud inventories. The encrypted B2
  package downloaded again, every artifact hash matched and all four inner
  SOPS archives decrypted successfully. This remains a pre-cutover capture.

The disposable in-cluster verification exposed failing OpenStack scratch volume
attachments and a Matrix Pod modifier that dropped the `tmp` volume used by
Velero's helper. The prepared Matrix controller now requests both PV/PVC
resource types and filesystem restore, and all three inert Pod replacements
retain `tmp`. All 27 Matrix tests passed; all three corrected Pods passed
Kubernetes server-side admission dry runs. Only audit-owned scratch resources
were removed, with UID and PVC/PV ownership checks. Other production writers remain running. Beets has a recorded writer freeze,
including a parent services Flux suspension so reconciliation cannot reset it.

The first host reinstall requires a working PiKVM session and identified host,
quiesced data exports for all retained filesystem claims/history and UniFi,
released/unclaimed-device dispositions, and final CNPG backup/WAL qualification.
Application operation checks follow restoration into the target and gate
release of each application. Forge cache and monitoring
history need explicit exports outside the current scheduled backup coverage.
Periodic AudioMuse dump-volume coverage also needs correction independently of
the new verified native dump. Backblaze presence or a Completed Velero backup
does not establish complete PVC coverage.

The full render/schema check after the Matrix fix passed: 33 entrypoints,
29 Flux stages, 1,194 validation instances and 443 Helm resources, with zero
failures. Auxiliary B2 exports were moved from an unsupported top-level
`migration/` directory into Velero's supported `plugins/migration/` directory.
Replacement versions were downloaded and verified before removing only the
exact original versions written by this audit. The unsupported prefix is empty,
and the backup location reports `Available` after a fresh validation.

An unrelated tracked edit appeared in main during the audit and was preserved.
Further source access uses the clean detached 8d5f130 checkout in the private
audit folder so that source capture cannot accidentally incorporate that edit.

## Cilium target revision, 12 October 2026

The owner requested Cilium while the migration recovery audit was active. The
prepared branch now pins Cilium 1.20.2, disables K3s kube-proxy, retains MetalLB
for Local traffic policies and keeps Multus for secondary IoT/guest interfaces.
Calico/Tigera manifests and duplicate Matrix/NetBird ordered policies are removed;
Forge and backup isolation rules are translated to Cilium. Managed gateway
backend selectors accompany retained VIP allowlists. Full offline schema validation passed for this revision: 33 entrypoints,
29 Flux stages, 1,189 validation instances and 464 Helm resources, with no
failures. Focused policy checks preserve API-only backup access, offline restore
and export isolation, CI private-network denial and managed identity gateway
routing. Physical Cilium datapath qualification remains required. No source
CNI or physical host was changed.

PiKVM ricotta was identified as the registered v2 unit, connected to pecorino.
An SSH-tunneled API session and harmless Shift press/release verified keyboard
control; an on-console host marker matched pecorino. Installer-media boot remains
unqualified. NetBird's 12 October Backblaze base backup and required WAL have
been independently downloaded and recovered with native PostgreSQL, followed by
configuration-count, index/heap and page-checksum checks. This is an online
recovery proof; final cutover exports and writer-stop receipts remain required.

Beets' 5 GiB cold RBD snapshot was exported as raw/gzip, age encrypted and stored
in Backblaze. The exact object version was downloaded, authenticated and hashed,
then restored with libguestfs into a fresh ext4 filesystem. All 22 entries matched
in data, UID/GID, mode and archived ACL/xattr metadata. Native SQLite integrity
passed for the 353-item/56-album catalog. The new `media/beets-data` claim keeps
its `/state` mount and UID/GID 1000. Its 353 relative catalog paths remain within the configured `/media/library` root;
media-library bytes are a separate outstanding recovery gate. This is the first
verified final cold claim export, not a complete migration backup. Its writer
and parent Flux holds remain recorded in the private recovery ledger.

The Cilium revision passed the combined Nix check with 280 tests, all-system
flake evaluation, formatter, strict native/Helm schema checks and the evaluated
K3s flags. The updated encrypted B2 checkpoint at 19:06 UTC downloaded and passed
authenticated decryption plus every artifact hash; it includes the one verified
final cold claim and keeps `cutoverReady: false`.


## Recorded source outage and independent recovery, 12 October 2026

Execution now has recorded reconciliation holds for infrastructure, services and
the CAPI management cluster. Application writers and schedulers are stopped;
provisioning and provider controllers are held. Original states, object UIDs and
termination proofs are in the private execution package. Source storage and cloud
APIs remain available for exports. No physical server has been reinstalled.

Final logical PostgreSQL exports for ZITADEL, Matrix, AudioMuse and NetBird have
been stored in Backblaze, downloaded, authenticated and restored with their
native PostgreSQL versions. Source row counts, role/table ownership, indexes and
page checks passed. Both CNPG clusters also passed independent base-backup/WAL
recovery beyond their recorded final application LSNs. ZITADEL's one unlogged
leadership row has the documented PostgreSQL recovery reset; every persistent
table matches, and the logical export retains the original row.

At 20:25 UTC, 12 of 50 source claims have verified final recovery exports. Beets,
both Wallos claims and the Forge cache passed fresh-filesystem restoration,
content/ownership/mode/ACL/xattr comparison and applicable SQLite integrity.
The remaining cold filesystem exports, including monitoring history, are active.
The media share has a separate final read-only archive and restore verification.
These counts are checkpoints; the private ledger records subsequent proofs.

UniFi shut down cleanly. Its complete standalone 64 GiB root export was stored
in Backblaze and downloaded/decrypted. An isolated local copy booted Ubuntu
24.04, started UOS/controller services and served loopback HTTPS with the original
origin certificate. The test had no outside network and left the pristine
source export unchanged. KubeVirt's two-NIC/cloud-init preparation is separate.

The held configuration capture passed every artifact hash and all four inner
SOPS archives after an independent Backblaze download. The four retained provider
states match the prepared lineages, serials and contents; retained credentials
and certificate fingerprints are unchanged. Independent SOPS-encrypted B2
access was qualified without relying on the source Kubernetes API.

Matrix's running source image digest is now pinned in application and restore
manifests. Its cached OCI image and the exact retained Linux runner/cache images
were independently stored in Backblaze, downloaded and restored with native
OCI tools, including every content digest. Source registry availability is no
longer required to recover these images.

The official NixOS minimal installer 26.05.11680.6fcc160353f6 was downloaded and
matched its published SHA-256. PiKVM media attachment/boot and all physical disk
changes remain pending. The backup gate remains closed while the remaining
claims, source recovery metadata and device dispositions are verified.


UniFi NoCloud transfer qualification at 20:57 UTC passed in a second isolated
boot. The prepared standalone raw disk clears the source OpenStack metadata
cache and only its generated Netplan file. The exact target user/network data
configured both fixed NIC MACs, services address 10.21.40.127 and its metric-50
default route. Controller HTTPS, machine ID, all three SSH host keys, bootstrap
version and origin certificate passed preservation checks. `ssh_deletekeys:
false` explicitly retains SSH identity when cloud-init sees a new instance.
The pristine Backblaze source disk and prepared backing image were unchanged by
the boot test. No physical LAN or host action was involved; pod DHCP and actual
KubeVirt networking remain live acceptance checks.

The reviewed installer is now stored on PiKVM. Its stored 1,738,014,720 bytes
matched the published SHA-256 again through the authorized SSH login. Virtual
media remains detached with the previous selection unchanged. Pecorino's exact
locked NixOS system closure also built successfully on the workstation.


## Cold guest archives and restartable transfers, 12 October 2026

The 21:15 UTC Backblaze checkpoint has 244 artifacts and verified final recovery
evidence for 28 of 50 source claims. Its exact version was downloaded,
authenticated and checked against all artifact hashes; the signed target Git
bundle passed native verification. The UniFi source disk and exact prepared
NoCloud two-NIC boot qualification are included. The private ledger continues
to require the remaining claim exports, cloud retirement archives and physical
recovery metadata before installation.

All three CAPI management guests shut down cleanly after their final held
configuration package was independently restored. That package contains 70
Secrets/ConfigMaps and 49 controller/CAPI objects. Their root RBD images are
being exported from owned cold snapshots; no source root has been deleted.
Four of eight retained source cloud images have independent Backblaze/native
QCOW2 conversion, integrity and full-byte comparison proofs. Owner-approved
Windows/macOS retirement remains separate from retained image recovery.

A network interruption aborted the large Forge backup-history upload. The
private transfer helper now records exact owned multipart IDs, per-part hashes
and confirmed ETags, and downloads exact versions in restartable ranges.
Interruption tests passed for multipart reuse, download retries, authenticated
recovery and changed-source refusal. The interrupted immutable archives resumed;
they are not counted as verified until native filesystem recovery passes.

Locked target system builds now pass for pecorino, taleggio and asiago. Prepared
installation files preserve each pinned source SSH host identity; the host age
key independently decrypts the target host secrets. Those private bootstrap
files are excluded from public Git and plaintext checkpoint artifacts. No
physical host activation, installer boot or disk reformat has occurred.


The execution branch now pins both CNPG bootstraps to their tested final base
backup IDs, end LSNs and source timelines. Those exact native recovery settings
already reached consistency and replayed through each final application writer
stop; both restored databases passed row-count and integrity checks. The target
Clusters have not been created. This prevents bootstrap from selecting a later
source backup implicitly while the source databases finish retiring.


## Verified execution checkpoint, 22:54 UTC on 12 October 2026

Independent final recovery evidence now covers 46 of 50 inventoried claims.
Each filesystem archive passed an exact Backblaze-version download, authenticated
decryption and restoration onto a fresh filesystem, with file hashes, numeric
ownership, modes, ACLs and xattrs compared. Native database recovery covers the
eight database-equivalent claims. The remaining four claims are Forgejo backup
history, both old physical Prometheus histories and Loki; their transfers and
native checks are still running. No physical installation gate has passed.

All eight retained Glance images and all seven retained unclaimed cloud cache
disks passed native disk conversion/integrity and full-byte comparison after
Backblaze recovery. Both unidentified cached images were preserved. All three
management guest roots and their cold etcd databases passed independent native
restoration. The six service guests shut down cleanly; their cold root archives
are in progress. Source images, root disks and data snapshots have not been
deleted.

Final OpenStack recovery includes a source-replica-pinned MariaDB logical dump,
its separate optimizer-statistics export and both native OVN databases. An
isolated MariaDB restore matched all 700 source tables and passed integrity
checks. The restored OVN northbound and southbound schemas, all persistent rows,
UUIDs and references match. All thirteen retired OpenStack claims also passed
fresh-filesystem restoration. Forty-five old cloud controllers are held, and
the four archived database/message-broker StatefulSets stopped gracefully. The
old OpenStack APIs are now stopped; Ceph and physical administration remain
available.

Cold Ceph monitor stores were captured one at a time, with full three-monitor
quorum restored between copies and the operator restored to its original
replica count. Each Backblaze download passed fresh-filesystem comparison and
independent native Ceph database copying. All enumerated keys and extracted
monitor, OSD and CRUSH maps match, including the original cluster FSID. These
checks started no replacement monitor or Ceph cluster.

The official installer remains detached on PiKVM. All three locked NixOS system
closures are built and protected by local GC roots. Source SATA identities match
the inventory; partition tables, RAID/LVM identities and four filesystem UUIDs
per host are recorded for cold root/boot/EFI archiving after installer boot.
Installer SSH identity decryption also works independently of the retiring
cluster, with the private key held only in memory. No physical server has been
rebooted, reformatted or activated with the target configuration.

The 22:54 Backblaze checkpoint contains 418 encrypted recovery artifacts and the
signed migration-branch bundle. Its exact object version was downloaded,
authenticated and verified against every artifact hash, and native Git bundle
verification passed. Later proofs are recorded in the private execution ledger.
Cilium 1.20.2 and kube-proxy replacement are prepared in the target branch;
physical CNI, Multus IoT, VIP and restored-application checks remain outstanding.

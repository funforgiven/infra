# Migration status

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

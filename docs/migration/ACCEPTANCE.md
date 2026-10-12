# Preparation acceptance

Scope: replace the OpenStack deployment in a separate NixOS/Kubernetes branch,
implement the migration code and document the future outage. This acceptance
does not authorize or certify live installation, data restoration or hardware.
The source is the frozen `8d5f1302de0cfa18f9575278f0b4a352c1ff4137` revision.

| Requirement | Implementation and evidence | Future execution gate |
| --- | --- | --- |
| Separate worktree/branch; main untouched | `/home/funforgiven/dev/infra-nixos-kubernetes`, `codex/nixos-kubernetes-migration`; final Git checks record main's clean tracked tree and original HEAD. | Publish the reviewed signed branch only when executing; no merge/push during preparation. |
| NixOS replaces the physical Ubuntu/cloud layer | Three [host configurations](../../deployments/homelab/hosts), flake-pinned K3s and one three-member embedded-etcd cluster; all nodes schedule apps. | Installer boot, host identity, SSH and API quorum checks. |
| Declarative disk layout | Mirrored SATA ESP/root disko and removable EFI boot, exact inventoried connector pairs; Ceph NVMe excluded. All server selections evaluate. | Confirm model/serial/connectors; qualify boot with either SATA member absent before relying on the mirror. |
| Preserve Rook-Ceph, simplify storage | Direct replicated RBD/CephFS on six NVMe disks, three host failure domains; cloud CSI/NFS provider layers removed. Snapshot CRDs/controller and RBD snapshot support are explicit. | Independently verified exports before fresh Ceph initialization or NVMe reuse; source monitor metadata archived separately. |
| Complete source inventory/removal rationale | [Inventory map](inventory-map.json): 798 documents, 74 source Flux stages, 24 provider files and 23 declared claims. Every document has a disposition, reason and existing target path. | New/missing live discoveries receive reviewed dispositions before retirement. |
| Preserve every service except native runners | Identity, monitoring, DNS/gateways, UniFi, home automation, games, media, Wallos, Forge/Linux CI, Matrix, NetBird and independent AWS mail all have target code. Native Windows/macOS runners have explicit owner-approved retirement. | Restore each service and qualify its existing identities/data; separately review application-repository CI requirements for retired native jobs. |
| Replace active cloud abstractions | Active OpenStack, Magnum, CAPI, cloud provisioning/runner brokers and in-cluster provider reconciliation removed. Four independent provider roots remain on the workstation. Source-reading capture and historical recovery records are explicitly scoped. | Stop source reconcilers/guests and release their actual address ownership after exports. |
| Preserve every identified volume/source | [DATA-MIGRATION.md](DATA-MIGRATION.md) covers 56 PVCs, 74 PVs, 65 Cinder devices, 11 Nova guests, 17 Glance images, one Manila share, released/unclaimed devices and additional host/control-plane/monitor archives. | Measure used bytes and staging capacity; export/check hashes and isolated restores, including ephemeral guest roots. Inventory metadata contains no application bytes. |
| Preserve databases and application state | Native CNPG recovery, PostgreSQL 17 Matrix dumps, PostgreSQL 15 AudioMuse dumps, SQLite/native archives, world/media/Forge data, UniFi cold raw image and radio datasets. Offline transfer/database bootstrap helpers reject unknown or inappropriate sources. | Final writer quiescence, native backup/LSN records and verified app/database restores. |
| Preserve IP/DNS/certificates and access | Actual Neutron/Octavia ownership mapped; retained VIPs and IoT addresses declared, old gateways released before MetalLB; four retained provider states and 54 encrypted certificate/account/state objects. One-time TLS seeding leaves renewal with cert-manager. | Fresh capture, fingerprint/expiry and state-lineage review; source ARP ownership gone, renewed target certificates/SSH/API trust checked. |
| Rebuild Home Assistant IoT attachment | Host VLAN 50, Multus/macvlan, existing HA/OTBR addresses, radios and managed proxy-CIDR migration; datasets/pairing retained. | Multicast/mDNS/IPv6, radio connectivity, restored integrations and Thread/Matter behavior on real hardware. |
| Retain supported UniFi environment | One KubeVirt Ubuntu guest with existing raw image/identity, direct `.40.127` NIC and filesystem-backed direct-CSI claim. | Cold image export, guest UID/image/network/cloud-init qualification and retained AP adoption/TLS/backups. |
| Clear lifecycle dependencies and recovery holds | One [Flux graph](../../deployments/homelab/cluster/waves.yaml), 29 semantic stages, explicit health/dependency checks and a recovery overlay. CNI/manual bootstrap and staged release are documented. | Establish networking and restored state before releasing writers; target backup/restore qualification after release. |
| Repeatable final source capture | `migration-source-capture` read-only qualification passed on actual source: 742 Secrets/ConfigMaps encrypted, compatible runtime/provider/TLS archives, nine hashed artifacts, 56 claims/74 PVs and complete paginated cloud/owner inventories. All files 0600, directory 0700; no overwrite or automatic Git input replacement. | Run fresh after source reconciliation freeze; review changes and preserve separate data/host/control-plane archives. |
| Nix/Kubernetes/provider validation | [VALIDATION.md](VALIDATION.md) records all-system flake evaluation, five host/four disko evaluations, combined Nix check, strict native/pinned Helm schemas, provider validation, helper checks and secret scanning. | Offline/schema checks do not simulate runtime admission, image startup, networking or hardware boot. Execute the documented pilots. |
| Document owner input and future live actions | [DECISIONS-REQUIRED.md](DECISIONS-REQUIRED.md): staging location/capacity, PiKVM access/ports, physical recovery availability and outage start. [RUNBOOK.md](RUNBOOK.md) contains all applies, writer freeze, installation, restore, qualification, retirement and rollback gates. | Owner supplies execution inputs; no live changes are part of this preparation. |

Residual source-only assets are intentional: encrypted old kubeconfigs, passwords,
provider state and archived native/source recovery evidence support rollback.
They have no active target cloud reconciler. Independent OpenAI/Hermes resources
have no active source owner and are left unchanged with encrypted state archived.
Optional host alert enrollment inputs live under the credential directory rather
than the cluster graph. The documentation/reference audit has no missing local
links in current repository guides.

Preparation is complete. Final broad verification passed on 2026-10-12:
all-system flake evaluation, five host/four disko evaluations, the combined Nix
check with 273 tests, full offline native/Helm validation (1,194 instances,
443 Helm resources, no failures/missing schemas), four provider validations,
46 enrollment tests, complete source capture/private compatibility and the
working-tree/history secret scan. Main's tracked tree remains clean at the
original source commit. The branch is committed locally for review; nothing
was published, merged or applied. Every live execution gate above remains
required for a separately authorized outage.

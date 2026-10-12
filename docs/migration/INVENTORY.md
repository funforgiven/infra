# Existing services and migration inventory

The source is commit `8d5f1302de0cfa18f9575278f0b4a352c1ff4137`. `inventory-map.json` maps every one of its 798 source document entries, including local Kustomize files, 74 Flux stages, 24 provider files and 23 explicit claims. It also maps all 56 captured live claims and 74 PVs individually, including released volumes and implicit chart/operator claims. These are declarative/read-only inventories, not proof of backup completeness or used-byte measurements.

Every removed entry has an explicit reason. A target path describes the surviving function; `matchingTargetObjects` records direct name/kind matches where they exist. Namespace changes, controller-managed resources and replaced cloud objects are identified by the architectural rule rather than falsely claiming identical API objects.

## Source function mapping

| Source group | Disposition | Replacement / justification |
| --- | --- | --- |
| `host-runtime/atollion-agents.sops.yaml` (1) | retained | Atollion agent/recovery credentials remain encrypted and available for Linux CI recovery. Targets: `deployments/homelab/credentials`, `deployments/homelab/cluster/apps/forge` |
| `host-runtime/matrix-forge-macos.sops.yaml` (1) | removed | The retired macOS runner bot/runtime is unnecessary after the owner-authorized runner removal; general Matrix alerts remain. Targets: `deployments/homelab/cluster/apps/matrix` |
| `host-runtime/unifi.sops.yaml` (1) | retained | Existing UniFi native guest runtime credentials are delivered through its encrypted cloud-init configuration. Targets: `deployments/homelab/credentials`, `deployments/homelab/cluster/apps/unifi` |
| `management/20-gitops` (1) | consolidated | One Flux installation owns the single bare-metal cluster; the guest management cluster is retired. Targets: `deployments/homelab/cluster/bootstrap/flux` |
| `management/30-backup` (4) | replaced | NixOS exports embedded-etcd snapshots and recovery keys off-server; CAPI management-cluster backup machinery is no longer required. Targets: `deployments/homelab/hosts/backup.nix` |
| `management/35-private-dns` (3) | consolidated | One retained private DNS VIP serves the existing homelab zones and aliases. This entry is a local Kustomize configuration document, not a live API object. Targets: `deployments/homelab/cluster/infrastructure/dns` |
| `management/40-capi` (35) | removed | K3s runs directly on the three NixOS hosts; Cluster API, CAPO, ORC, kubeadm providers, addon controller and their qualification objects no longer manage guest clusters. This entry is a local Kustomize configuration document, not a live API object. Targets: `deployments/homelab/hosts` |
| `management/bootstrap` (2) | consolidated | Bootstrap credentials and Git source are consolidated into the single target Flux installation. This entry is a local Kustomize configuration document, not a live API object. Targets: `deployments/homelab/cluster/bootstrap/flux` |
| `management/kustomization.yaml` (1) | consolidated | Numbered old cluster wrappers, namespaces and waves are consolidated into one semantic Flux dependency graph; service-specific mappings identify preserved functions. This entry is a local Kustomize configuration document, not a live API object. Targets: `deployments/homelab/cluster` |
| `management/waves.yaml` (2) | consolidated | Numbered old cluster wrappers, namespaces and waves are consolidated into one semantic Flux dependency graph; service-specific mappings identify preserved functions. Targets: `deployments/homelab/cluster` |
| `services/10-platform-controllers` (6) | consolidated | Duplicate platform controllers become one cert-manager/Envoy installation for the single cluster. Targets: `deployments/homelab/cluster/infrastructure/controllers` |
| `services/11-iot-network` (8) | consolidated | Multus and physical IoT VLAN attachment remain; old guest-node policy is replaced by NixOS host networking. This entry is a local Kustomize configuration document, not a live API object. Targets: `deployments/homelab/cluster/infrastructure/multus`, `deployments/homelab/cluster/apps/home-automation/network-attachment.yaml` |
| `services/12-observability` (9) | consolidated | The workload and physical-cluster monitoring stacks become one stack; all source persistent data has a separate disposition. Targets: `deployments/homelab/cluster/infrastructure/observability` |
| `services/15-backup-controller` (3) | consolidated | Velero/Kopia and the existing B2 destination retain application backup lifecycles using direct CSI classes. This entry is a local Kustomize configuration document, not a live API object. Targets: `deployments/homelab/cluster/infrastructure/velero` |
| `services/16-backup-policy` (25) | retained | Application schedules, hooks and restore qualification remain; cloud storage handles are never rebound to a different CSI driver. Targets: `deployments/homelab/cluster/infrastructure/backups` |
| `services/20-platform-gateway` (15) | retained | Private/public Envoy gateways retain names, VIPs, TLS and application routes with MetalLB ownership. Targets: `deployments/homelab/cluster/infrastructure/gateway` |
| `services/24-unifi` (11) | retained | Native UniFi OS application, controller identity, AP adoption, TLS, metrics and backups remain in the supported KubeVirt guest. Targets: `deployments/homelab/cluster/apps/unifi` |
| `services/25-home-automation` (24) | retained | Home Assistant/Matter/MQTT/Zigbee/Thread state, integrations, static IoT addresses and radios remain; network attachment is rebuilt through Multus/macvlan. Targets: `deployments/homelab/cluster/apps/home-automation` |
| `services/30-factorio` (6) | retained | Factorio worlds, credentials, mods and the port-preserving external address remain. Targets: `deployments/homelab/cluster/apps/factorio` |
| `services/31-valheim` (5) | consolidated | Valheim worlds, identity and external ports remain with direct RBD storage and restore qualification. This entry is a local Kustomize configuration document, not a live API object. Targets: `deployments/homelab/cluster/apps/valheim` |
| `services/40-media` (37) | retained | Navidrome, SFTPGo, Beets, AudioMuse/PostgreSQL/Redis, Discord music and the shared media library remain; Manila NFS becomes direct CephFS. Targets: `deployments/homelab/cluster/apps/media` |
| `services/45-wallos` (17) | consolidated | Wallos SQLite database, uploaded logos and existing OIDC client remain. This entry is a local Kustomize configuration document, not a live API object. Targets: `deployments/homelab/cluster/apps/wallos` |
| `services/46-forge` (80) | retained | Forgejo repositories/database/LFS/packages, signing, Linux/Atollion CI, cache and app recovery remain; native Windows/macOS objects have explicit exceptions. Targets: `deployments/homelab/cluster/apps/forge` |
| `services/47-matrix` (53) | retained | Synapse, MAS, Element, PostgreSQL, media, signing/session keys and encrypted relay state remain. Targets: `deployments/homelab/cluster/apps/matrix` |
| `services/48-netbird` (63) | retained | NetBird server/PostgreSQL, STUN, Kubernetes operator, routing/DNS and access policies remain. Targets: `deployments/homelab/cluster/apps/netbird` |
| `services/50-synthetic-monitoring` (6) | retained | Application and public-edge availability probes remain in the consolidated monitoring stack. Targets: `deployments/homelab/cluster/infrastructure/synthetic-monitoring` |
| `services/kustomization.yaml` (1) | consolidated | Numbered old cluster wrappers, namespaces and waves are consolidated into one semantic Flux dependency graph; service-specific mappings identify preserved functions. This entry is a local Kustomize configuration document, not a live API object. Targets: `deployments/homelab/cluster` |
| `services/namespaces.yaml` (20) | consolidated | Numbered old cluster wrappers, namespaces and waves are consolidated into one semantic Flux dependency graph; service-specific mappings identify preserved functions. Targets: `deployments/homelab/cluster` |
| `services/waves.yaml` (19) | consolidated | Numbered old cluster wrappers, namespaces and waves are consolidated into one semantic Flux dependency graph; service-specific mappings identify preserved functions. Targets: `deployments/homelab/cluster` |
| `undercloud/20-backup` (4) | replaced | The physical Kubernetes control plane is replaced by K3s embedded etcd and host-level off-server recovery backups. Targets: `deployments/homelab/hosts/backup.nix` |
| `undercloud/20-gitops` (79) | consolidated | Three old Flux/control-plane graphs become one semantic graph with explicit dependencies and a restore overlay. Targets: `deployments/homelab/cluster/bootstrap/flux`, `deployments/homelab/cluster/waves.yaml` |
| `undercloud/30-rook-ceph` (24) | replaced | Rook-Ceph is retained with direct RBD/CephFS CSI; new Ceph identities/pools replace cloud pools after independently verified data exports. Targets: `deployments/homelab/cluster/infrastructure/rook`, `deployments/homelab/cluster/infrastructure/ceph`, `deployments/homelab/cluster/infrastructure/storage` |
| `undercloud/32-identity-controllers` (9) | retained | CloudNativePG and its Barman plugin retain PostgreSQL backup, restore and failover lifecycles. Targets: `deployments/homelab/cluster/infrastructure/databases` |
| `undercloud/33-identity-data` (12) | retained | ZITADEL PostgreSQL restores its original database and owner from the verified source backup/WAL archive. Targets: `deployments/homelab/cluster/apps/identity/database` |
| `undercloud/34-identity` (5) | consolidated | ZITADEL, its master key, login material, domain and surviving client IDs remain. This entry is a local Kustomize configuration document, not a live API object. Targets: `deployments/homelab/cluster/apps/identity/server` |
| `undercloud/34-identity-configuration` (6) | replaced | Workstation OpenTofu with preserved state replaces in-cluster OpenTofu reconciliation and output-copy wrappers. Targets: `components/homelab/providers/identity`, `deployments/homelab/credentials` |
| `undercloud/34-identity-qualification` (2) | consolidated | Native database recovery qualification plus explicit OIDC/API checks replace tests against retired control planes. This entry is a local Kustomize configuration document, not a live API object. Targets: `deployments/homelab/cluster/apps/identity/database/restore-test.yaml`, `docs/migration/RUNBOOK.md` |
| `undercloud/35-observability` (11) | consolidated | A single monitoring stack retains Grafana/Loki and monitoring functions; existing duplicate Prometheus/Alertmanager data is migrated or archived explicitly in the volume map. Targets: `deployments/homelab/cluster/infrastructure/observability` |
| `undercloud/36-observability-integrations` (4) | consolidated | One Alertmanager retains Telegram, Matrix and email integration credentials and routing. Targets: `deployments/homelab/cluster/infrastructure/observability`, `deployments/homelab/cluster/apps/matrix` |
| `undercloud/37-service-network` (12) | replaced | Cilium pod networking and kube-proxy replacement, MetalLB announcements and NixOS VLANs replace cloud service-network staging and host-cloud reconciliation. Targets: `deployments/homelab/cluster/infrastructure/cilium`, `deployments/homelab/cluster/infrastructure/metallb`, `deployments/homelab/cluster/infrastructure/load-balancers`, `deployments/homelab/hosts/common.nix` |
| `undercloud/38-service-api-foundation` (41) | consolidated | One cert-manager/Envoy/MetalLB/DNS installation retains application endpoints, ACME account and management TLS; cloud API endpoints are retired separately. Targets: `deployments/homelab/cluster/infrastructure/controllers`, `deployments/homelab/cluster/infrastructure/dns`, `deployments/homelab/cluster/infrastructure/gateway`, `deployments/homelab/cluster/infrastructure/load-balancers` |
| `undercloud/40-openstack-infrastructure` (14) | removed | OpenStack MariaDB, RabbitMQ, OVN databases and cloud shared infrastructure are unnecessary when apps and CSI run directly on bare-metal Kubernetes; archive their state for rollback. Targets: `deployments/homelab/hosts`, `deployments/homelab/cluster/infrastructure/cilium` |
| `undercloud/50-openstack-core` (26) | removed | Keystone, Nova, Neutron, Glance, Placement and their cloud APIs/control plane are retired; Kubernetes scheduling, native networking and direct CSI provide the retained workloads. Targets: `deployments/homelab/hosts`, `deployments/homelab/cluster/infrastructure/storage` |
| `undercloud/55-external-network` (3) | removed | Neutron/OVN external-network machinery is replaced by host VLANs, bridges, MetalLB and the retained RouterOS network policy. Targets: `deployments/homelab/hosts/common.nix`, `deployments/homelab/cluster/infrastructure/load-balancers` |
| `undercloud/60-openstack-services` (20) | removed | Cinder, Manila, Octavia and cloud service plumbing are replaced by direct RBD/CephFS CSI and MetalLB/Envoy; source bytes must be exported before cloud retirement. Targets: `deployments/homelab/cluster/infrastructure/storage`, `deployments/homelab/cluster/infrastructure/load-balancers` |
| `undercloud/70-capi-management-infrastructure` (3) | removed | No guest management Kubernetes cluster is needed; the three bare-metal K3s servers own application lifecycles. This entry is a local Kustomize configuration document, not a live API object. Targets: `deployments/homelab/hosts` |
| `undercloud/71-magnum` (6) | removed | Magnum no longer provisions guest Kubernetes clusters; NixOS declares the single physical cluster. Targets: `deployments/homelab/hosts` |
| `undercloud/72-management-uis` (5) | removed | OpenStack dashboard/UI functions are retired with the cloud APIs; SSH, Kubernetes/Flux and retained Grafana provide target operations. This entry is a local Kustomize configuration document, not a live API object. Targets: `docs/migration/RUNBOOK.md` |
| `undercloud/80-magnum-workload` (2) | removed | Guest workload-cluster provisioning is replaced by the single bare-metal cluster; no application is removed by this wrapper retirement. This entry is a local Kustomize configuration document, not a live API object. Targets: `deployments/homelab/hosts` |
| `undercloud/81-services-foundation` (10) | replaced | Cloud tenant/flavor/quota and in-cluster OpenTofu foundation abstractions are retired; encrypted concrete app inputs, independent provider state and direct storage remain. Targets: `deployments/homelab/credentials`, `components/homelab/operations`, `deployments/homelab/cluster/infrastructure/storage` |
| `undercloud/82-services-cluster` (16) | replaced | NixOS/K3s and one Flux bootstrap replace CAPI/Magnum guest worker/control-plane lifecycle and associated enrollment jobs. Targets: `deployments/homelab/hosts`, `deployments/homelab/cluster/bootstrap/flux` |
| `undercloud/83-services-hosts` (2) | consolidated | Home automation is a Kubernetes workload, UniFi retains one supported KubeVirt Ubuntu guest, and independent AWS mail remains; generic cloud-host deployment wrappers are removed. This entry is a local Kustomize configuration document, not a live API object. Targets: `deployments/homelab/cluster/apps/home-automation`, `deployments/homelab/cluster/apps/unifi`, `components/nix/servers/mail-aws.nix` |
| `undercloud/84-mail-aws` (4) | replaced | Existing AWS EC2/EIP/RDS/S3/IAM/monitoring resources keep preserved provider state; workstation OpenTofu replaces the cluster-hosted reconciler. Targets: `components/homelab/providers/mail-aws`, `components/nix/servers/mail-aws.nix` |
| `undercloud/85-service-dns` (6) | consolidated | Existing Cloudflare records remain under workstation OpenTofu with their original state, names and addresses. This entry is a local Kustomize configuration document, not a live API object. Targets: `components/homelab/providers/dns` |
| `undercloud/85-unifi` (2) | consolidated | The cold-exported supported UniFi Ubuntu guest becomes one KubeVirt VM with the same services address and native UOS data. This entry is a local Kustomize configuration document, not a live API object. Targets: `deployments/homelab/cluster/apps/unifi` |
| `undercloud/86-forge-foundation` (2) | removed | The CI cloud tenant, flavors, network and quota foundation is unnecessary for Linux Kubernetes job runners; Forgejo, cache and artifact services remain. This entry is a local Kustomize configuration document, not a live API object. Targets: `deployments/homelab/cluster/apps/forge` |
| `undercloud/87-forge-runners` (3) | removed | Native Windows/macOS VM runners and their OpenStack provisioning are removed at the owner’s explicit request; Linux CI remains. Targets: `deployments/homelab/cluster/apps/forge` |
| `undercloud/88-netbird-policy` (5) | replaced | NetBird account, groups, policies and DNS remain under workstation OpenTofu with preserved state and restored server database. Targets: `components/homelab/providers/netbird`, `deployments/homelab/cluster/apps/netbird` |
| `undercloud/kustomization.yaml` (1) | consolidated | Numbered old cluster wrappers, namespaces and waves are consolidated into one semantic Flux dependency graph; service-specific mappings identify preserved functions. This entry is a local Kustomize configuration document, not a live API object. Targets: `deployments/homelab/cluster` |

## Every live claim

Production files restore into newly provisioned `ceph-block` or `ceph-filesystem` claims. Native PostgreSQL recovery creates its own new claims. The source handle belongs to its old storage driver and must never be repointed to direct Rook CSI. The machine-readable file also gives every PV handle and its disposition.

| Source cluster | Claim | Requested size | Action | Destination |
| --- | --- | --- | --- | --- |
| services | `backup-qualification-restore/backup-canary` | 1Gi | rebuild-qualification | `backup-qualification-restore/backup-canary` |
| services | `backup-qualification/backup-canary` | 1Gi | rebuild-qualification | `backup-qualification/backup-canary` |
| services | `finance/wallos-database` | 2Gi | filesystem-restore | `finance/wallos-database` |
| services | `finance/wallos-logos` | 2Gi | filesystem-restore | `finance/wallos-logos` |
| services | `forge-cache/forge-cache` | 320Gi | filesystem-restore | `forge-cache/forge-cache` |
| services | `forge/forgejo-backups` | 800Gi | filesystem-restore | `forge/forgejo-backups` |
| services | `forge/forgejo-data` | 80Gi | filesystem-restore | `forge/forgejo-data` |
| services | `games-restore/data-factorio-0` | 20Gi | rebuild-qualification | `games-restore/data-factorio-0` |
| services | `games-restore/data-valheim-0` | 20Gi | rebuild-qualification | `games-restore/data-valheim-0` |
| services | `games/data-factorio-0` | 20Gi | filesystem-restore | `games/data-factorio-0` |
| services | `games/data-valheim-0` | 20Gi | filesystem-restore | `games/data-valheim-0` |
| services | `home-automation-restore/automation-backups` | 20Gi | rebuild-qualification | `home-automation-restore/automation-backups` |
| services | `home-automation-restore/thread-backups` | 1Gi | rebuild-qualification | `home-automation-restore/thread-backups` |
| services | `home-automation/automation-backups` | 20Gi | filesystem-restore | `home-automation/automation-backups` |
| services | `home-automation/automation-state` | 20Gi | filesystem-restore | `home-automation/automation-state` |
| services | `home-automation/thread-backups` | 1Gi | filesystem-restore | `home-automation/thread-backups` |
| services | `home-automation/thread-state` | 1Gi | filesystem-restore | `home-automation/thread-state` |
| services | `matrix/matrix-dumps` | 5Gi | filesystem-restore | `matrix/matrix-dumps` |
| services | `matrix/matrix-media` | 20Gi | filesystem-restore | `matrix/matrix-media` |
| services | `matrix/matrix-postgres` | 20Gi | database-recovery | `matrix/matrix-postgres` |
| services | `matrix/matrix-relay` | 2Gi | filesystem-restore | `matrix/matrix-relay` |
| services | `media/audiomuse-postgres` | 20Gi | database-recovery | `media/audiomuse-postgres` |
| services | `media/audiomuse-postgres-dumps` | 5Gi | filesystem-restore | `media/audiomuse-postgres-dumps` |
| services | `media/beets-data` | 5Gi | filesystem-restore | `media/beets-data` |
| services | `media/discord-music-data` | 5Gi | filesystem-restore | `media/discord-music-data` |
| services | `media/media-library` | 1Ti | filesystem-restore | `media/media-library` |
| services | `media/navidrome-data` | 20Gi | filesystem-restore | `media/navidrome-data` |
| services | `media/sftpgo-data` | 5Gi | filesystem-restore | `media/sftpgo-data` |
| services | `netbird/netbird-postgres-1` | 10Gi | database-recovery | `netbird/netbird-postgres-1` |
| services | `netbird/netbird-postgres-2` | 10Gi | database-recovery | `netbird/netbird-postgres-2` |
| services | `netbird/netbird-postgres-3` | 10Gi | database-recovery | `netbird/netbird-postgres-3` |
| services | `services-observability/alertmanager-kube-prometheus-stack-alertmanager-db-alertmanager-kube-prometheus-stack-alertmanager-0` | 2Gi | filesystem-restore | `services-observability/alertmanager-kube-prometheus-stack-alertmanager-db-alertmanager-kube-prometheus-stack-alertmanager-0` |
| services | `services-observability/prometheus-kube-prometheus-stack-prometheus-db-prometheus-kube-prometheus-stack-prometheus-0` | 20Gi | filesystem-restore | `services-observability/prometheus-kube-prometheus-stack-prometheus-db-prometheus-kube-prometheus-stack-prometheus-0` |
| infrastructure | `identity/zitadel-postgres-1` | 10Gi | database-recovery | `identity/zitadel-postgres-1` |
| infrastructure | `identity/zitadel-postgres-2` | 10Gi | database-recovery | `identity/zitadel-postgres-2` |
| infrastructure | `identity/zitadel-postgres-3` | 10Gi | database-recovery | `identity/zitadel-postgres-3` |
| infrastructure | `observability/alertmanager-kube-prometheus-stack-alertmanager-db-alertmanager-kube-prometheus-stack-alertmanager-0` | 2Gi | archive-and-merge-silences | `services-observability/alertmanager-kube-prometheus-stack-alertmanager-db-alertmanager-kube-prometheus-stack-alertmanager-0` |
| infrastructure | `observability/alertmanager-kube-prometheus-stack-alertmanager-db-alertmanager-kube-prometheus-stack-alertmanager-1` | 2Gi | archive-and-merge-silences | `services-observability/alertmanager-kube-prometheus-stack-alertmanager-db-alertmanager-kube-prometheus-stack-alertmanager-0` |
| infrastructure | `observability/alertmanager-kube-prometheus-stack-alertmanager-db-alertmanager-kube-prometheus-stack-alertmanager-2` | 2Gi | archive-and-merge-silences | `services-observability/alertmanager-kube-prometheus-stack-alertmanager-db-alertmanager-kube-prometheus-stack-alertmanager-0` |
| infrastructure | `observability/kube-prometheus-stack-grafana` | 10Gi | filesystem-restore | `services-observability/kube-prometheus-stack-grafana` |
| infrastructure | `observability/prometheus-kube-prometheus-stack-prometheus-db-prometheus-kube-prometheus-stack-prometheus-0` | 50Gi | archive-history | Independent archive |
| infrastructure | `observability/prometheus-kube-prometheus-stack-prometheus-db-prometheus-kube-prometheus-stack-prometheus-1` | 50Gi | archive-history | Independent archive |
| infrastructure | `observability/storage-loki-0` | 50Gi | filesystem-restore | `services-observability/storage-loki-0` |
| infrastructure | `openstack/data-ovn-ovsdb-nb-0` | 5Gi | archive-then-retire | Independent archive |
| infrastructure | `openstack/data-ovn-ovsdb-nb-1` | 5Gi | archive-then-retire | Independent archive |
| infrastructure | `openstack/data-ovn-ovsdb-nb-2` | 5Gi | archive-then-retire | Independent archive |
| infrastructure | `openstack/data-ovn-ovsdb-sb-0` | 5Gi | archive-then-retire | Independent archive |
| infrastructure | `openstack/data-ovn-ovsdb-sb-1` | 5Gi | archive-then-retire | Independent archive |
| infrastructure | `openstack/data-ovn-ovsdb-sb-2` | 5Gi | archive-then-retire | Independent archive |
| infrastructure | `openstack/mariadb-backup-data` | 20Gi | archive-then-retire | Independent archive |
| infrastructure | `openstack/mysql-data-mariadb-server-0` | 20Gi | archive-then-retire | Independent archive |
| infrastructure | `openstack/mysql-data-mariadb-server-1` | 20Gi | archive-then-retire | Independent archive |
| infrastructure | `openstack/mysql-data-mariadb-server-2` | 20Gi | archive-then-retire | Independent archive |
| infrastructure | `openstack/rabbitmq-data-rabbitmq-rabbitmq-0` | 5Gi | archive-then-retire | Independent archive |
| infrastructure | `openstack/rabbitmq-data-rabbitmq-rabbitmq-1` | 5Gi | archive-then-retire | Independent archive |
| infrastructure | `openstack/rabbitmq-data-rabbitmq-rabbitmq-2` | 5Gi | archive-then-retire | Independent archive |

## Cloud disks, guests and images

Read-only cloud inspection also captured 65 Cinder volumes, 11 Nova guests, 17 Glance images, 1 Manila share and 13 floating IPs. Every volume/guest/image has an individual disposition in `inventory-map.json`. This includes unclaimed volumes absent from the PV list and the unattached Windows boot device identified by its source image metadata. No byte exports have been performed.

The UniFi root is `a7dbe35a-ddfa-41fe-ae76-13481f3bc8c6`, 64Gi, attached to Nova guest `294f80d3-6e79-4760-a527-29f49296938f`. The shared 1Ti media share is `fcbda35a-8a7e-443c-97fa-5f9732a1ba85`; its old NFS export is recorded in `live-cloud-volume-inventory.json`. Source guest roots not shown as Cinder devices require their Nova/libvirt backend identity before source Ceph can be retired.

Forty-one TLS Secrets, twelve provider state Secrets and the ACME account key are captured in `secrets/source-certificates-and-state.sops.yaml`. Public fingerprints, expiry and state serial/lineage metadata are in `live-certificate-state-inventory.json`. Seed only surviving app TLS/account material before cert-manager starts; cluster-specific webhook/database/control-plane certificates regenerate. Do not apply the entire source archive as a Kubernetes bundle.


## Every cloud floating IP

The port/load-balancer ownership is captured in `live-address-owner-inventory.json`. All thirteen addresses have individual dispositions; a Neutron port marked DOWN can still represent an ONLINE OVN/Octavia VIP and does not prove ARP ownership is gone. The actual guest workload API uses `.40.197`; `.40.121` is an obsolete desired/reserved guest-API endpoint, not the observed allocated floating IP.

| Source address | Captured owner | Action | Target |
| --- | --- | --- | --- |
| `10.21.40.124` | `kube_service_services-v1-gxs3ybwuh5vh_games_valheim` | preserve-address-transfer-ownership | games/valheim |
| `10.21.40.100` | `capi-management-api` | replace-cloud-control-plane-endpoint | 10.21.20.128 |
| `10.21.40.123` | `kube_service_services-v1-gxs3ybwuh5vh_games_factorio` | preserve-address-transfer-ownership | games/factorio |
| `10.21.40.125` | `forge-windows` | owner-approved-native-runner-address-retirement | Retired after archive/owner gate |
| `10.21.40.122` | `kube_service_services-v1-gxs3ybwuh5vh_envoy-gateway-system_envoy-services-network-services-8c92eb20` | preserve-address-transfer-ownership | services Envoy / Forge SSH |
| `10.21.40.129` | `kube_service_services-v1-gxs3ybwuh5vh_netbird_netbird-stun` | preserve-address-transfer-ownership | netbird/netbird-stun |
| `10.21.40.126` | `forge-macos` | owner-approved-native-runner-address-retirement | Retired after archive/owner gate |
| `10.21.40.127` | `unifi` | preserve-address-transfer-ownership | unifi/unifi services NIC |
| `10.21.40.197` | `k8s-clusterapi-cluster-magnum-12ae0943a6c74034a6f3aea7956ff5ac-services-v1-gxs3ybwuh5vh-kubeapi` | replace-cloud-control-plane-endpoint | 10.21.20.128 |
| `10.21.40.102` | `capi-management-2` | archive-management-guest-then-retire-address | Retired after archive/owner gate |
| `10.21.40.101` | `capi-management-1` | archive-management-guest-then-retire-address | Retired after archive/owner gate |
| `10.21.40.128` | `kube_service_services-v1-gxs3ybwuh5vh_envoy-gateway-system_envoy-services-network-matrix-public-f7302c1a` | preserve-address-transfer-ownership | public Envoy / Matrix and NetBird HTTPS |
| `10.21.40.103` | `capi-management-3` | archive-management-guest-then-retire-address | Retired after archive/owner gate |

## Sources outside the PVC list

- Cold UniFi VM boot volume and its source Nova/Cinder identity.
- All other Nova/Glance/Cinder/Manila volumes and snapshots, including unattached or released data not represented by a Kubernetes PVC.
- All old provider backend states, Ceph FSID/mon maps/keyrings/CRDs and /var/lib/rook monitor state on OS disks.
- Complete host disk/OS recovery archives before reinstall; old cluster etcd snapshots and bootstrap credentials.
- Generated TLS certificate/private-key Secrets and app signing/session credentials absent from desired-state YAML.

These additional exports are mandatory cutover gates. The prepared inventory does not claim that live VM disks, monitor-state archives have already been copied. Generated TLS/account/provider Secrets are captured in the separately encrypted source archive; refresh them immediately before cutover. Independent AWS mail is retained in place, with existing provider state, RDS/S3 recovery and stable EIP; its storage is not a local Ceph migration.

## Address and certificate ownership

| Address / identity | Target owner and migration treatment |
| --- | --- |
| `10.21.20.10–12`, `10.21.30.10–12` | Same three physical hosts; NixOS management/Ceph VLANs. Preserve Ed25519 SSH host identity. |
| `10.21.20.128` | K3s API, host keepalived. Stop the old API owner before reuse. Existing kubeconfig CA changes with the rebuilt cluster. |
| `10.21.20.129` | Private CoreDNS, MetalLB. Same DNS forwarder address and service zones. |
| `10.21.20.131` | Retained management HTTPS Envoy gateway for ZITADEL/Grafana. Preserve ACME account and certificate/key. |
| `10.21.20.130` | Retired OpenStack API gateway. No application is moved onto this obsolete endpoint. Retire its DNS/certificate after archive verification. |
| `10.21.40.120` | Home Assistant HTTP-only LAN Service on 8123. IoT address is separate. The old Ubuntu guest SSH endpoint is retired. |
| `10.21.40.121` | Retired guest Kubernetes API; the physical API is `10.21.20.128`. Do not reuse while an old owner remains. |
| `10.21.40.122` | Private application HTTPS Envoy gateway. Preserve names, public/private DNS and corresponding TLS Secrets. |
| `10.21.40.123`, `.124` | Factorio/Valheim MetalLB Services, same UDP ports and RouterOS WAN/hairpin mappings. |
| `10.21.40.125`, `.126` | Retired native Windows/macOS runner addresses. Forgejo SSH and cache remain on the services gateway at `.122`; remove old runner access rules and reserve these retired addresses outside MetalLB pools. |
| `10.21.40.127` | UniFi guest services NIC on `br-services`; reserve outside MetalLB pools and remove the old Neutron FIP owner first. |
| `10.21.40.128` | Public Envoy for Matrix/NetBird, existing WAN 80/443 forwarding. |
| `10.21.40.129` | NetBird STUN UDP Service. |
| `10.21.50.10`, `.11`, `.20`, `.21` | HA pod, separate OTBR pod, Zigbee RCP and Thread RCP. Preserve VLAN/radio addresses and pairing/network datasets. |
| Cloudflare / AWS mail / OIDC IDs | Retain existing state and external identities. Never apply these providers against an empty state. |
| Generated app TLS, signing/session and E2E keys | Export encrypted before shutdown, restore before applications, verify fingerprint/identity. A source manifest alone does not contain every generated key. |

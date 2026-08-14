# Homelab OpenStack cloud

This directory describes the desired architecture for a three-node,
hyperconverged private cloud. It is a design and bootstrap workspace; component
configuration is not an installation claim until its readiness gate passes.

## Current stage

The live deployment boundary is summarized below. Flux readiness is not used
as the only proof; the referenced waves also have their service-specific tests
and readiness gates in Git.

| Wave | State | Current evidence |
| ---: | --- | --- |
| 00–10 | Complete | Three Ubuntu hosts, healthy OS RAID1, 2×25 GbE LACP per host, Kubernetes 1.35.4, kube-vip, and Cilium |
| 20 | Complete | Encrypted undercloud etcd backup in B2 with separate restore authorization and a tested isolated restore |
| 30 | Complete | Rook 1.20.3, Ceph 20.2.2, six OSDs, three monitors, RBD pools, CephFS, and NFS-Ganesha report healthy |
| 35–38 | Complete | Prometheus, Alertmanager, Grafana, Loki, Fluent Bit, internal DNS, private Gateway API, cert-manager, and the MetalLB rollback path |
| 40 | Complete | OpenStack-Helm exclusively owns three-member MariaDB Galera and RabbitMQ clusters; TLS and service tests pass |
| 50–55 | Complete | Keystone, Glance, Cinder, Placement, Nova, Neutron, OVN, libvirt, Open vSwitch, the external provider network, and encrypted off-cluster authoritative-state recovery |
| 60–63 | Complete | Heat, Octavia, Manila, and Barbican are deployed with their chart and semantic tests passing |
| 70 | Complete | Three management VMs, HA k3s, Flux, encrypted B2 etcd recovery, cert-manager, CAPI, CAPO, and the add-on provider are qualified |
| 80 | Complete | A real Magnum cluster passed create, scale-up, worker replacement, Kubernetes 1.35.6→1.36.2 upgrade, Cinder RWO, Manila RWX, no-tenant-Ceph, management-outage, and clean-deletion tests |
| 90 | Complete | Supervised `pecorino` OSD replacement and `asiago` one-host-loss recovery passed; physical independent-OS-disk boot proof is an accepted residual risk |

All five live-migration workload classes have passed every directed host pair.
The initial production acceptance boundary is complete through wave 90.

The small set of current documents is intentional:

| File | Purpose |
| --- | --- |
| [`versions.yaml`](versions.yaml) | Exact selected versions, commits, images, and digests; selections are not installation claims |
| [`backup-destination.yaml`](backup-destination.yaml) | Public B2 bucket and least-privilege writer contract; contains no credential value or application-key ID |
| [`network-inventory.yaml`](network-inventory.yaml) | Live Ansible inventory consumed by RouterOS automation; includes qualified physical link facts |
| [`omada-network.yaml`](omada-network.yaml) | Omada desired state and qualification boundary |
| [`declarative-ownership.yaml`](declarative-ownership.yaml) | Single-controller ownership map for cloud, service, identity, DNS, monitoring, and backup state |
| [`manual-exceptions.yaml`](manual-exceptions.yaml) | Validated register for unavoidable UI/bootstrap state, its backup, drift probe, and exit criterion |
| [`hosts/`](hosts/) | Ubuntu inventory and replacement-tolerant physical slot contracts |
| [`kubernetes/`](kubernetes/) | Pinned Kubespray bootstrap and semantic acceptance contract |
| [`undercloud/`](undercloud/) | Flux root for the real undercloud cluster |
| [`undercloud/38-service-api-foundation/`](undercloud/38-service-api-foundation/) | Private Gateway, certificate, and mutually exclusive L2 fallback operation |
| [`undercloud/81-services-foundation/`](undercloud/81-services-foundation/) | Suspended OpenTofu reconciliation for the self-hosted services project, network, flavors, and quotas |
| [`undercloud/82-services-cluster/`](undercloud/82-services-cluster/) | Suspended Magnum and signed-Flux bootstrap reconciler with ephemeral kubeconfig handling |
| [`services/`](services/) | Independent Flux root for self-hosted applications; initially Karakeep full-text retrieval only |

Future platform resources are added only when their installation wave is
reached. A proposed service is recorded here as desired architecture, not as a
placeholder custom resource or fake-ready manifest.

The installed API set includes Keystone, Glance, Cinder, Placement, Nova,
Neutron, Heat, Octavia, Manila, and Barbican. Magnum opens only after its
separate management plane is recoverable and semantically ready.
Swift/S3-compatible object service waits for dedicated disks; optional
services are not installed merely to resemble AWS on day one.

## Identity and access

One three-replica ZITADEL service at `https://auth.cloud.fahrican.com` is the
root identity provider for the management plane. ZITADEL authenticates people;
each target remains responsible for authorization. The `Infrastructure`
project defines `infra-admin` and `infra-viewer`, which map to Grafana roles and
the `fahrican:infra-admin` and `fahrican:infra-viewer` Kubernetes groups.
OpenStack projects remain Keystone resource boundaries and are not mirrored as
ZITADEL organizations.

Grafana and OpenStack each use their own confidential OIDC client. Keystone
maps the ZITADEL administrator and viewer identities into Keystone groups and
roles while continuing to own OpenStack project authorization; Skyline exposes
the resulting `openid` WebSSO choice. The undercloud and CAPI
management clusters use separate public clients and native Kubernetes
`AuthenticationConfiguration` claim mappings. Certificate kubeconfigs, the
Grafana local administrator, and the ZITADEL `iam-breakglass` human remain
available when OIDC is unavailable. The permanent OpenTofu controller uses a
scoped ZITADEL machine key; the IAM-owner PAT in `secrets/zitadel.yaml` is
admin-only offline recovery material and is never deployed.

The digest-pinned Keystone image contains the distribution-packaged
`mod_auth_openidc`; no runtime package installation or side-loaded Apache module
is used. A periodic, idempotent reconciler owns the Keystone groups, mapping,
identity provider, and `openid` federation protocol. ZITADEL is the credential
authority: no Google or other external social identity provider is configured,
and users may register passkeys directly in ZITADEL.

## Authority and ownership

Git is the reproducible desired-state authority. The unavoidable host layer is
kept small and has one owner:

- supervised firmware and OS installation through PiKVM;
- Ansible for Ubuntu packages, time, KVM/IOMMU, storage
  slot validation, Netplan, and the host-side bond/VLAN configuration;
- RouterOS/Omada automation for physical switching and routing;
- pinned Kubespray for Kubernetes, kube-vip, and the bootstrap Cilium install;
- Flux for Kubernetes resources after the API and CNI are healthy;
- sops-nix with age on the NixOS operator host, and Flux SOPS decryption with a
  separate per-cluster age identity inside Kubernetes.

OpenTofu owns OpenStack, external-cloud, DNS, ZITADEL, and provider-supported
external-service resources. NixOS owns standalone hosts and system services.
Pinned API reconcilers are used only where a provider is unavailable but a
stable API exists. A remote resource must have exactly one owner; an existing
resource is imported before it is reconciled.

Manual or UI configuration is permitted only when no practical declarative
interface exists. Every such case must be present in `manual-exceptions.yaml`,
include an encrypted backup or regeneration procedure, have a non-secret drift
probe, and define the condition under which the exception is removed. An
emergency remote change is investigated before reconciliation and either
backported to Git immediately or reverted through its declared owner.

No ordinary convergence run may repartition a disk, initialize an OSD, flash
firmware, update RouterOS, reset Kubernetes, or bootstrap Flux merely because a
file exists. Those operations require explicit, reviewed entry points and
retained evidence.

## Physical design

Every server is intended to be a Kubernetes control-plane/worker, OpenStack
control/compute/network node, and Ceph host failure domain.

| Host | Processor | RAM | Host storage | Ceph storage |
| --- | --- | ---: | --- | --- |
| `pecorino` | Intel Core i9-14900K | 64 GiB | 2×256 GB SATA RAID1 | 2×2 TB NVMe |
| `taleggio` | Intel Core i5-13600K | 96 GiB | 2×256 GB SATA RAID1 | 2×2 TB NVMe |
| `asiago` | AMD Ryzen 9 9900X | 64 GiB | 2×256 GB SATA RAID1 | 2×2 TB NVMe |

The accepted lab failure domains include consumer CPUs, non-ECC RAM, non-PLP
NVMe, one 25 GbE adapter per host, one CRS510, and no automated UPS shutdown.
They must remain visible risks in acceptance evidence.

Disk desired identity is the physical connector path, not the replaceable
device serial. Host networking requires exactly two devices using the qualified
`ice` driver; interface name, PCI slot, and permanent MAC are observations. The
switch-facing identity remains the host's assigned CRS510 LAG. Replacing
compatible media in the same disk connector or moving/replacing a compatible
NIC must not require a Git identity change.

## Network design

Both 25 GbE ports form one active/fast 802.3ad `bond0`, with a layer-3+4 hash and
`min-links=1`, matched by a CRS510 LAG. This was chosen over dedicating one link
to Ceph: every traffic class survives one link failure and independent flows can
use 50 Gb/s aggregate, while one flow remains limited to 25 Gb/s.
The CRS server-member ports use a 9216-byte L2 frame ceiling so the 9000-byte
bond and tagged east-west VLAN MTUs are real rather than merely declared.

| VLAN | Purpose | MTU | Reachability |
| ---: | --- | ---: | --- |
| 20 | Hosts, Kubernetes API, private service VIPs | 1500 | Routed through `10.21.20.1` |
| 30 | Ceph public and cluster traffic | 9000 | CRS510-local; no gateway |
| 31 | Nova live migration | 9000 | CRS510-local; no gateway |
| 32 | OVN Geneve underlay | 9000 | CRS510-local; no gateway |
| 33 | Manila NFS service provider network | 1500 | CRS510-local; no gateway |
| 40 | Neutron external/Floating IP provider network | 1500 | Selected north-south through CCR2004 |
| 90 | Physical management | 1500 | Routed management only |

VLAN 90 reserves `10.21.90.1` for the CCR2004, `.2` for the CRS510, `.3` for
PiKVM `ricotta`, `.4` for the EAP670, and `.5` for the SG3210XHP-M2. These
are fixed allocations outside any endpoint DHCP pool; `.3` and `.5` are
delivered by static DHCP reservations.
The SG3210XHP-M2 additionally retains `192.168.90.5/24` as a DHCP-failure
recovery address on its VLAN-90 management interface.

VLAN 33 is the live Manila service network. Host automation owns
`bond0.33`/`br-manila`, and CRS reconciliation carries it only between the
three server bonds. It has no CCR2004 gateway or northbound route.

Ceph, migration, Geneve, Manila data, and other east-west flows must never use
the CCR2004. Its current 1 Gb/s core uplink carries WAN-bound traffic and
selected north-south forwarding only. Backups to B2 are intentionally WAN-bound.

The OVN tenant limit for an IPv4 Geneve path is explicit:

```text
9000 underlay - 20 outer IPv4 - 38 OVN Geneve allowance = 8942 bytes
```

The undercloud Cilium design uses native routing on the 1500-byte node network,
so its pod MTU is 1500. An initial tenant Kubernetes overlay uses a 1500-byte
Neutron network minus a 50-byte VXLAN allowance, giving pod MTU 1450. The jumbo
tenant option is separately qualified at 8942/8892.

### Service VIPs and DNS

Cilium remains the target CNI, kube-proxy replacement, LB IPAM controller, and
primary L2 announcer. L2 announcement is accepted only after unique VIP
ownership, API reachability, failover, and multi-interface selection pass.
Services use `externalTrafficPolicy: Cluster`.

MetalLB L2 is the documented rollback if Cilium VIP ownership, API connectivity,
or multi-interface qualification fails. It does not replace Cilium as the CNI.
The two L2 owners are mutually exclusive; rollback first prunes the active
owner, proves no ARP owner remains, then enables the alternate owner without
changing Service addresses, Gateway API, Envoy Gateway, or DNS.

`cloud.fahrican.com` uses split-horizon DNS:

- a three-replica internal CoreDNS service at `10.21.20.129` is authoritative
  for private Envoy and service VIPs, with RouterOS forwarding the private zone;
- `10.21.20.130` terminates HTTPS for private OpenStack APIs and
  `10.21.20.131` terminates HTTPS for administrator web interfaces;
- public Cloudflare DNS contains only deliberately approved public endpoints;
- public external-dns may consume only explicit, Git-owned public endpoint
  records and must not infer targets from private Services or Gateways;
- Cloudflare DNS-01 credentials may create `_acme-challenge` TXT records but do
  not authorize endpoint publication. The initial public endpoint set is empty.

The initial browser-facing management endpoints are private-only:

| Service | URL |
| --- | --- |
| ZITADEL account and sign-in | `https://auth.cloud.fahrican.com` |
| OpenStack Skyline | `https://dashboard.cloud.fahrican.com` |
| Grafana | `https://grafana.cloud.fahrican.com` |

Prometheus, Alertmanager, Loki, Ceph, MariaDB, RabbitMQ, and the Kubernetes API
remain direct administrative backends rather than additional web routes.

### Manila NFS

Tenant-facing NFS never uses Ceph VLAN 30. `physnet-manila` is a flat Neutron
provider network on VLAN 33 through `br-manila`/`bond0.33`. Ganesha VIPs use
`10.21.33.20-39`; tenant secondary ports use DHCP `10.21.33.40-254`; the subnet
has no gateway. Approved projects receive provider-network RBAC, and clients
receive only NFSv4.1 TCP 2049 access to the qualified VIP. Router attachment is
unsupported and must fail semantic drift checks.

## Storage design

Rook manages exactly six raw NVMe OSDs across three host failure domains. Every
replicated pool uses size 3, minimum size 2, host failure domains, and PG
autoscaling. Each OSD has a 4 GiB memory target/request and a 6 GiB limit.

Separate RBD pools serve Glance images, Cinder volumes, Nova ephemeral disks,
and Cinder Backup. Manila uses a dedicated CephFS metadata pool and data pool,
one active MDS with one host-separated standby, plus Rook NFS-Ganesha. The exact
Rook and Ceph patch/image selection is in `versions.yaml`; Ceph 20.2.0 is
forbidden.

Cinder Backup's Ceph pool is a fast local recovery copy, not an independent
disaster backup. Selected Glance, Cinder, and CephFS recovery points must be
exported off the Ceph failure domain.

### Undercloud etcd recovery

Every six hours, one control-plane node takes and validates an etcd snapshot,
encrypts it client-side with SOPS and a dedicated age recipient, then replaces
`undercloud/etcd/snapshot.db.sops.json` in the private B2 bucket. Replacing one
stable key keeps the newest recovery point current while B2 retains hidden
older versions for 30 days. The rule never expires the latest version merely
because the cluster stops uploading.

The cluster contains only the upload-only B2 key and the public age recipient.
The separate B2 reader and age identity remain admin-only SOPS recovery
material and are never injected into Kubernetes. A restore operator lists
object versions, downloads a selected version plus its metadata, verifies the
ciphertext SHA-256 metadata, decrypts it in temporary storage, and runs
`etcdutl snapshot status` before use. Qualification restores into a temporary
data directory and starts an isolated loopback-only etcd; it never replaces a
live member. Plaintext snapshots, temporary credentials, and restored data are
removed after the gate.

A disaster restore stops all old etcd members first, restores one selected
snapshot with the Kubespray-pinned etcd 3.6.10 tooling and the intended member
topology, then re-adds or rebuilds the other members. Flux reconciliation opens
only after quorum, Kubernetes API encryption, the API VIP, Cilium, and the
signed Git revision have all been re-qualified.

Tenant Kubernetes clusters consume Cinder CSI for block storage and Manila CSI
over NFS for shared storage. Supported templates do not expose cephx keys,
monitor addresses, Ceph CSI, or VLAN 30. Rook/Ceph-on-Cinder is explicitly
unsupported because it would build Ceph on virtual volumes already backed by
the same Ceph cluster.

OpenStack Swift is the deferred object-storage service. It is not installed on
day one and must wait for dedicated failure-domain-aware raw disks. Swift on
Cinder RBD or CephFS is prohibited; Ceph RGW is not the competing public object
service.

## OpenStack ownership and CPU compatibility

Upstream OpenStack-Helm is the sole OpenStack lifecycle implementation.
MariaDB Galera is owned only by the upstream OpenStack-Helm `mariadb` chart;
RabbitMQ is owned only by the upstream `rabbitmq` chart. Both target three
host-spread replicas. Percona XtraDB Cluster Operator and RabbitMQ Cluster
Operator are forbidden. OpenStack service charts own database/user/vhost
provisioning and schema jobs; cert-manager owns certificates; backup jobs use
supported export interfaces without owning database or broker topology.

The MariaDB chart writes a restore-verified logical backup to its dedicated
20 GiB PVC every day and retains three days locally. The authoritative backup
CronJob exports the newest passed archive off-cluster together with atomic OVN
Northbound and Southbound snapshots. RabbitMQ queues are non-authoritative
transport state and are not backed up: service charts recreate users and
virtual hosts from Git, while durable service state remains in MariaDB. Do not
add a second database or broker operator to solve recovery.

### Authoritative OpenStack recovery

At 01:17 UTC, `openstack-authoritative-backup` requires a non-empty MariaDB
archive and its OpenStack-Helm `.passed` sentinel, takes atomic OVN NB and SB
backups, records checksums, and writes one versioned bundle. SOPS encrypts the
bundle with age before the upload-only credential replaces
`undercloud/openstack/authoritative.tar.sops.json`. B2 retains hidden replaced
versions for 30 days and never expires the latest version merely because
uploads stop.

The cluster credential can only write that object prefix. The separate reader
under `undercloud/openstack_restore_reader` in `secrets/backblaze.yaml` can
only list and read the same prefix; the age identity remains outside
Kubernetes. Treat MariaDB, OVN NB, and OVN SB from one bundle as one recovery
point.

For a supervised restore:

1. Select and download one B2 version with the offline reader, verify its
   `ciphertext-sha256` object metadata, then decrypt it in temporary storage.
2. Extract the bundle and run `sha256sum -c SHA256SUMS` before reading any
   payload.
3. Import `mariadb.openstack.all.sql` and every grant file into an isolated
   MariaDB 11.4 instance first, then require `mariadb-check --all-databases`.
4. Boot copies of both OVN database files with the pinned OVN image and query
   `NB_Global` and `SB_Global`; do not force a schema conversion.
5. Only after isolated validation, quiesce OpenStack writers, restore the live
   MariaDB and the matching NB/SB pair, then reopen services in dependency-wave
   order and rerun their semantic gates.
6. Remove plaintext SQL, database files, credentials, and restored data from
   temporary storage after the recovery gate.

The 2026-08-08 qualification downloaded the object through the offline reader,
verified all bundle checksums, imported and checked 14 application databases,
and booted isolated OVN NB schema 7.3.0 and SB schema 20.33.0 directly from the
downloaded backups.

Nova starts with the common custom CPU model `Westmere`, the named model exposed
by all three hosts that provides the intended x86-64-v2-era AES baseline; host
passthrough is forbidden. This baseline has passed the full migration matrix.
The live libvirt model catalogue was compared across all three hosts on
2026-08-06. Their common usable named-model intersection reaches
`IvyBridge-IBRS`; the v3-era Haswell and Broadwell models are not usable on the
AMD host, the EPYC models are not usable on the Intel hosts, and this QEMU
catalogue exposes no generic `x86-64-v3` model. `x86-64-v3` therefore remains
disabled. Do not synthesize it with a hand-maintained feature list; reassess
the named-model intersection after a QEMU/libvirt upgrade. Nova initially
reserves 32 GiB of every 64 GiB host and uses `ram_allocation_ratio=1.0` until
measured one-host-loss headroom justifies a change.

The idle, CPU-loaded, AES-256-GCM, repeated disk-write, and network-stream
workloads passed the six directed `pecorino`, `taleggio`, and `asiago` host
pairs on 2026-08-06. Every migration completed on the requested host and the
post-migration workload and sentinel checks passed. During each network-stream
migration, a rate-limited 512 MiB transfer retained its SHA-256 checksum while
800 tenant-overlay probes and 400 floating-IP probes completed with zero packet
loss. The streams completed in 48.7–51.1 seconds while their Nova operations
completed in 24–30 seconds, proving that Nova operation time was not guest
downtime. Ceph remained `HEALTH_OK` after the matrix.

## Magnum bootstrap and recovery

Magnum depends on healthy core OpenStack; it cannot be part of initial
undercloud bootstrap. The target sequence is:

1. A Git-owned Heat definition creates three anti-affined management VMs with
   durable Cinder system volumes and an Octavia API endpoint.
2. Ansible creates an HA k3s cluster with embedded etcd.
3. A separate Flux root installs CAPI, CAPO, add-on controllers, and monitoring.
4. Magnum writes open only after semantic CAPI readiness.

The management kubeconfig is SOPS-encrypted, etcd snapshots are encrypted and
copied to B2, and recovery recreates the VM stack, restores etcd, bootstraps
Flux, rotates credentials, and proves CAPO ownership before Magnum is enabled.
On 2026-08-06, the scheduled upload completed with an upload-only key. A
separate prefix-restricted reader downloaded the object, matched its recorded
SHA-256, decrypted it with the admin-only age identity, and restored revision
269076 into a temporary loopback-only etcd that passed endpoint health. No
reader or age private key is present in the management cluster.
Magnum API and conductor readiness both require a successful request to the
management Kubernetes API. An outage therefore removes the Magnum API from its
Service endpoints and prevents conductors from being considered ready, while
already-running workload clusters continue independently. On 2026-08-07, a
controlled management-API outage reduced both components from three ready
replicas to zero and removed all Magnum Service endpoints; the existing
workload cluster remained five-for-five Ready and retained both storage
sentinels. Restoring the Git-owned router policy returned the API, conductors,
and all three endpoints without changing the workload cluster.

Calico is the initial workload-cluster CNI target because it is the regularly
tested upstream path. Cilium remains a preview template requiring its own MTU,
policy, load-balancer, replacement, and upgrade matrix. No template is published
until Cinder CSI, Manila CSI, NFS-only security, node-port `/32` access
reconciliation, and lifecycle tests are complete.

The upstream Magnum driver supplies Cinder CSI values directly. Its pinned
workload chart also supports Manila CSI, but the driver does not yet expose that
chart option. The qualification cluster therefore receives its Manila add-on
as a Git-owned Azimuth `HelmRelease` in the Magnum project namespace; a second
add-on operator or a local driver fork is not part of the initial platform.
The live Calico cluster has three control-plane nodes and two workers. It has
passed Cinder RWO and Manila RWX provisioning, cross-pod sentinel reads, a
one-to-two-worker scale-up, and checks proving that neither a Ceph CSI driver
nor a Rook/Ceph namespace exists in the tenant cluster. A controller-managed
worker replacement returned the cluster to five Ready nodes; a read-only pod
then mounted both existing claims on the replacement node and read their
original sentinels. A one-node-at-a-time upgrade then moved all three
control-plane nodes and both workers from Kubernetes 1.35.6 to 1.36.2 while
preserving those Cinder and Manila sentinels. Replacement control-plane nodes
wait 40 seconds before kubeadm joins so OVN has time to remove an unhealthy new
API member from the load-balancer pool. Deleting the healthy cluster through
Magnum then removed its CAPI objects, five Nova servers, Octavia load balancer,
Neutron resources, floating IP, and disposable CSI backends without affecting
the retained failed cluster. This completes the initial Calico template's
lifecycle matrix; publishing it remains an operational product decision.

## Reconciliation, readiness, and dependency graphs

Flux ordering and Kubernetes `Ready` conditions are necessary but insufficient.
Every wave stops at semantic readiness implemented, when the wave exists, by a
Kubernetes Job, Helm test, Prometheus success window, or a narrowly justified
controller. Evidence is retained before a later wave is enabled.

Installation is deliberately sequential:

```text
00 physical → 10 Kubernetes → 20 GitOps + off-cluster backup foundation
→ 30 Rook/Ceph + backup → 35 observability → 36 Ceph monitoring
→ service/API network foundation
→ 40 MariaDB/RabbitMQ + backup → 50 OpenStack core + backup
→ 60 OpenStack services + backup → 70 Magnum/CAPI + backup
→ 80 restore/recovery acceptance → 90 production acceptance
```

Major upgrades use separate commits and hold points:

```text
00 compatibility + restored backup → 10 hosts/Kubernetes
→ 20 Cilium/VIPs → 30 Rook/Ceph → 40 database/messaging
→ 50 OpenStack core → 60 OpenStack services → 70 CAPI/Magnum
→ 80 observability + full acceptance
```

Each major-upgrade wave requires a compatibility change, rendered diff, fresh
backup and disposable restore, preflight, rollout, semantic gate, and rollback
boundary. Stateful services never downgrade automatically. Schema expansion
precedes new service pods; contracting migrations wait until the rollback
window closes. The dependency graphs and semantic hold points above are the
architecture authority; executable gates are added only with their wave.

The private B2 destination and its upload-only credential are created without
Object Lock. That credential is not a recovery credential: it cannot read or
list objects. Each stateful component deploys its backup with the component;
wave 20 also requires an explicit lifecycle and cost policy plus separately
controlled restore authorization. Wave 80 is the isolated restore and recovery
acceptance gate, not the first time backups exist.

Wave 35 selects the digest-pinned `kube-prometheus-stack` 88.0.1 chart,
Grafana-community Loki 18.7.0 (Loki 3.7.4), and Fluent
`fluent-bit-collector` 1.0.9 (Fluent Bit 5.0.9). Prometheus has two
host-separated 50 GiB RBD-backed replicas with 15-day retention; Alertmanager
has three host-separated replicas; Grafana has one 10 GiB RBD-backed replica.
Loki uses its supported monolithic filesystem mode: one 50 GiB RBD-backed pod
with 14-day retention. Ceph preserves its PVC across a host loss, but log
ingestion and queries have a pod-reschedule RTO; Fluent Bit therefore keeps a
bounded filesystem buffer on every node. Three monolithic replicas are not
claimed because the selected Loki chart requires an object-storage backend for
that topology, and this wave deliberately adds neither RGW nor MinIO. Metrics
and logs share the Ceph failure domain they observe, so a whole-Ceph outage also
removes their historical data until Ceph recovers. OpenSearch remains deferred
until measured retention/search demand and one-host-loss memory headroom
justify it.

Wave 72 adds three host-spread Skyline API replicas and routes Skyline and
Grafana through the dedicated management Gateway. Skyline uses the existing
OpenStack-Helm MariaDB and Keystone ownership model. Grafana deliberately stays
at one replica because its current RBD-backed SQLite database is single-writer;
high availability would require a separate shared database and is deferred
until the operational need justifies it.

Wave 36 keeps Rook's dynamic ServiceMonitor ownership disabled and instead
Git-owns one manager monitor, one exporter monitor, and a compact selection of
the exact Rook 1.20.3 alert expressions. The scrape boundary adds the stable
`cluster=rook-ceph` label required by those expressions. This avoids installing
a second Ceph chart merely to obtain monitoring resources.

### Semantic hold points

The minimum evidence at each boundary is behavioral:

| Area | Required proof |
| --- | --- |
| Physical network | Both LACP members at 25 Gb/s with the selected FEC; each-member failure; 1472-byte and 8972-byte DF paths; no east-west hop through CCR2004 |
| Kubernetes | Three-member etcd quorum, API VIP ownership, Cilium connectivity, and exactly one L2 service-VIP owner |
| Ceph | Six OSDs up/in, three-monitor quorum, no degraded PGs, RBD and CephFS write tests, one-host-loss recovery |
| MariaDB | Three-member Galera Primary component with every member Synced |
| RabbitMQ | All expected nodes, no partition or alarm, expected definitions, and publish/consume |
| OpenStack | Keystone token plus disposable Glance, Cinder, Nova, Neutron, Heat, Octavia, Manila, and Masakari operations appropriate to the wave |
| Nova CPU | Five workload types live-migrate through all six directed host pairs |
| Magnum | Management outage closes writes, existing clusters continue, and create/scale/upgrade/replace/delete plus CSI tests pass |
| Backup | Checksums, bucket/prefix scope, encryption, lifecycle policy, and restore authorization are valid; an isolated restore succeeds inside policy |

### Accepted residual risks

Physical boot with either OS disk absent was not exercised. Each host has two
distinct EFI system partitions, synchronized bootloader trees, and clean
two-member RAID1 arrays for `/boot` and the root volume, but actual firmware
and OS startup after physical removal of either disk remains unverified. This
is accepted for the current production boundary. The shared rebuild-media
template is inventory-rendered and qualified for every current host. VLAN 40,
the Neutron bridge mapping, the external network, and
floating-IP behavior are qualified. VLANs 30-33 have no northbound path, and
Manila uses the dedicated VLAN 33 Ganesha endpoint rather than Ceph VLAN 30.

Internal DNS, Cilium service-VIP ownership and failover, certificate issuance,
Gateway API, Envoy Gateway, and the mutually exclusive MetalLB rollback are
qualified. No public API endpoint is currently approved. The bucket
intentionally has no Object Lock and therefore makes no immutability claim.

The qualification project has a 12-instance, 24-core, and 60 GiB RAM quota so
the five-node Magnum upgrade can surge one control-plane and one worker at a
time. On 2026-08-08, `pecorino` `osd.0` on the declared
`pci-0000:04:00.0-nvme-1` connector was marked out, fully backfilled, confirmed
safe to destroy, purged, wiped, and automatically recreated by Rook. The
cluster returned to six OSDs up and in with all 257 placement groups
active+clean, while Kubernetes, OpenStack, Flux, monitoring, and the CAPI
management cluster remained healthy.

Also on 2026-08-08, `asiago` was powered off without draining. The two
surviving Kubernetes and etcd members kept the API ready; Ceph retained monitor
quorum with every placement group active, and disposable RBD and CephFS writes
passed while four of six OSDs were available. Galera remained Primary and
Synced with two members, RabbitMQ retained two running nodes without alarms or
partitions, the OpenStack APIs and private service VIPs remained reachable,
and the CAPI management cluster rescheduled all controllers onto its two
surviving VMs. After `asiago` returned, Ceph recovered to `HEALTH_OK` with all
257 placement groups active+clean, its Nova guest resumed, and both clusters
returned to full readiness. The returning MariaDB member required removal of
its stale `tc.log` and recreation of only that pod after the two surviving
members were verified Primary and Synced; it then rejoined through state
transfer. The post-reboot host preflight passed all 22 checks without changes.

Scheduled encrypted MariaDB and OVN upload, 30-day hidden-version retention,
separately authorized download, and isolated restore are qualified. Production
acceptance is complete through wave 90, subject to the accepted physical
OS-disk boot risk above.
Swift and a highly available long-term log backend remain capacity-driven later
work, not blockers for the initial private-cloud API.

## Flux bootstrap, backups, and rebuild

Pinned Kubespray now creates Kubernetes, kube-vip, and Cilium. After their
semantic gate passes, the pinned Flux controllers are installed, the
cluster-specific age key is injected out of band, and Flux begins reconciling
the Git source. Flux reads the public repository over HTTPS without a Git
credential and verifies the checked-out `HEAD` against the committed SSH
signing public key.

Bootstrap and recovery use the same small sequence: apply the committed Flux
controllers and public signing-key Secret through a control-plane host's
root-owned kubeconfig, inject `/run/secrets/undercloud-flux-age-identity` as
`flux-system/sops-age` without writing a kubeconfig or plaintext key to disk,
then apply the committed Git source and root Kustomization. Completion requires
all four controller Deployments to be Available, the GitRepository to be Ready
with `sourceVerificationMode=HEAD`, and the GitRepository and Kustomization to
converge at the expected signed commit revision. The SOPS identity is stable
recovery state and is not regenerated during a host or cluster rebuild.

Repository convention stays shallow: reusable implementation belongs in
`components/cloud/<component>/`; concrete resources belong in
`deployments/homelab/cloud/<cluster>/<wave>/`. Each real Kubernetes cluster gets
one Flux root when it is bootstrapped, including the separate Magnum management
cluster. A directory appears only with its first real resource.

The independent recovery destination is a private, SSE-B2-encrypted B2 bucket.
Object Lock is disabled by design, so this destination does not claim immutable
or ransomware-resistant retention. Separate writers are restricted to the
undercloud etcd, OpenStack, and management etcd prefixes and `writeFiles`; they
cannot read, list, delete, change retention, or administer the bucket. Separate
restore readers and age identities are SOPS-encrypted admin-only material
outside Kubernetes. Automated six-hour uploads and bounded hidden-version
retention are enabled for both etcd backups, and the authoritative OpenStack
bundle is uploaded daily; recovery still requires supervised access to the
corresponding reader.

Current off-cluster coverage includes undercloud etcd, Magnum-management etcd,
MariaDB, ZITADEL PostgreSQL, and a matched OVN Northbound/Southbound pair. A
weekly isolated test restores ZITADEL PostgreSQL, starts the pinned ZITADEL
binary with the recovered master key, verifies discovery and signing keys, then
deletes the temporary database and volumes. The remaining data-policy work is
selected tenant-data export outside the Ceph failure domain. RabbitMQ message
bodies are not a backup payload: users and virtual hosts are recreated from Git
and authoritative service state comes from MariaDB. Restore evidence, not
object existence alone, is the readiness condition.

A full rebuild starts from Git, PiKVM, pinned installation artifacts, the host
inventory, offline age identities, supervised B2 restore authorization, and
retained slot evidence. Preserved Ceph devices may be adopted only after they resolve to the
declared physical slots and match the reviewed recovery observation. No
destructive rebuild step may infer its target from a device name or serial.

## References

- [OpenStack-Helm](https://docs.openstack.org/openstack-helm/latest/) is the
  primary chart and service-layout implementation.
- [Neutron MTU guidance](https://docs.openstack.org/neutron/latest/admin/config-mtu.html)
  and the [OVN install guide](https://docs.openstack.org/neutron/latest/install/ovn/manual_install.html)
  define the Geneve allowance.
- [Open vSwitch OVSDB backup and recovery](https://docs.openvswitch.org/en/latest/ref/ovsdb.7/)
  defines the atomic online snapshot and restore mechanism used for OVN.
- [VEXXHOST Atmosphere](https://github.com/vexxhost/atmosphere) informs host
  preflight, version catalogues, HA tests, and Magnum/CAPI operations.
- [Genestack](https://github.com/rackerlabs/genestack) informs OpenStack-Helm
  composition, Kubespray/Rook layering, observability, and upgrade sequencing.
- [YAOOK](https://docs.yaook.cloud/) informs semantic dependencies,
  maintenance interlocks, and lifecycle conditions. Its operators are not
  adopted.
- [Rook](https://rook.io/docs/rook/latest-release/),
  [Cilium](https://docs.cilium.io/en/stable/), and
  [Magnum CAPI Helm](https://docs.openstack.org/magnum-capi-helm/latest/) remain
  the component references.

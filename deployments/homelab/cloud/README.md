# Homelab OpenStack cloud

This directory describes the desired architecture for a three-node,
hyperconverged private cloud. It is a design and bootstrap workspace; component
configuration is not an installation claim until its readiness gate passes.

## Current stage

Automated physical qualification and Kubernetes bootstrap wave 10 are
complete. Ubuntu is installed and Git-managed on all three servers. Every host
passes the hardware, RAID/EFI, KVM/IOMMU, LACP/FEC, routed-MTU, all-direction
jumbo-path, and individual-LACP-member failure gates. Kubernetes 1.35.4 has a
healthy three-member etcd quorum, a qualified kube-vip API endpoint, and a
healthy Cilium native-routing dataplane. Independent-OS-disk boot testing is
deliberately deferred as a resilience exercise. The switch map is `taleggio`
on ports 3/4, `asiago` on 5/6, and `pecorino` on 7/8. GitOps wave 20 is next;
production eligibility remains false.

The small set of current documents is intentional:

| File | Purpose |
| --- | --- |
| [`versions.yaml`](versions.yaml) | Exact selected versions, commits, images, and digests; selections are not installation claims |
| [`network-inventory.yaml`](network-inventory.yaml) | Live Ansible inventory consumed by RouterOS automation; includes qualified physical link facts |
| [`omada-network.yaml`](omada-network.yaml) | Omada desired state and qualification boundary |
| [`hosts/`](hosts/) | Ubuntu inventory and replacement-tolerant physical slot contracts |
| [`kubernetes/`](kubernetes/) | Pinned Kubespray bootstrap and semantic acceptance contract |
| [`undercloud/`](undercloud/) | Flux root for the real undercloud cluster |

Future platform resources are added only when their installation wave is
reached. A proposed service is recorded here as desired architecture, not as a
placeholder custom resource or fake-ready manifest.

The first usable API provides Keystone, Glance, Nova, Neutron, and Cinder—the
private-cloud equivalents of IAM, images, EC2, VPC, and EBS. Octavia, Manila,
Heat, and Magnum follow in later waves. Swift/S3-compatible object service waits
for dedicated disks; optional services are not installed merely to resemble
AWS on day one.

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
| `taleggio` | Intel Core i5-13600K | 64 GiB | 2×256 GB SATA RAID1 | 2×2 TB NVMe |
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

VLAN 33 is an allocated Manila contract, not a physical-wave prerequisite. It
is absent from current host Netplan and CRS reconciliation and is introduced
with `bond0.33`/`br-manila` only when the Manila service wave opens.

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
- public Cloudflare DNS contains only deliberately approved public endpoints;
- public external-dns may consume only explicit, Git-owned public endpoint
  records and must not infer targets from private Services or Gateways;
- Cloudflare DNS-01 credentials may create `_acme-challenge` TXT records but do
  not authorize endpoint publication. The initial public endpoint set is empty.

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

Nova starts with the common custom CPU model `x86-64-v2-AES`; host passthrough is
forbidden. `x86-64-v3` remains a disabled candidate until idle, CPU-loaded, AES,
disk-write, and network-stream guests migrate successfully in every direction
between all three hosts. Nova initially reserves 32 GiB of every 64 GiB host and
uses `ram_allocation_ratio=1.0` until measured one-host-loss headroom justifies a
change.

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
Flux, rotates credentials, and proves CAPO ownership before writes reopen. When
the management plane is unhealthy, reads may remain available but mutating
Magnum requests return 503 and conductors scale to zero. Writes require ten
continuous healthy minutes before reopening.

Calico is the initial workload-cluster CNI target because it is the regularly
tested upstream path. Cilium remains a preview template requiring its own MTU,
policy, load-balancer, replacement, and upgrade matrix. No template is published
until Cinder CSI, Manila CSI, NFS-only security, node-port `/32` access
reconciliation, and lifecycle tests are complete.

## Reconciliation, readiness, and dependency graphs

Flux ordering and Kubernetes `Ready` conditions are necessary but insufficient.
Every wave stops at semantic readiness implemented, when the wave exists, by a
Kubernetes Job, Helm test, Prometheus success window, or a narrowly justified
controller. Evidence is retained before a later wave is enabled.

Installation is deliberately sequential:

```text
00 physical → 10 Kubernetes → 20 GitOps + off-cluster backup foundation
→ 30 Rook/Ceph + backup → 35 observability
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

The B2 Object Lock destination and recovery credentials are a wave-20
prerequisite. Each stateful component deploys its backup with the component;
wave 80 is the isolated restore and recovery acceptance gate, not the first
time backups exist.

Wave 35 installs `kube-prometheus-stack` (Prometheus Operator, Alertmanager,
Grafana) with node, Kubernetes, Ceph, and OpenStack exporters. Alloy or Fluent
Bit sends initial logs to Loki. OpenSearch is deferred until measured
retention/search demand and one-host-loss memory headroom justify it; Loki and
OpenSearch do not become duplicate permanent log stores without distinct,
documented roles.

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
| Backup | Checksum and Object Lock are valid and an isolated restore succeeds inside policy |

### Remaining gates

Independent-OS-disk boot proof remains a deferred resilience gate. The shared
rebuild-media template is inventory-rendered and qualified for every current
host. VLAN 40 is deliberately deferred to the Neutron external-network wave and
does not block Kubernetes bootstrap; its later acceptance must prove that VLANs
30–33 do not leak northbound.

Before GitOps or service waves open, choose separate age recipients, commit only
SOPS ciphertext, qualify immutable chart/controller artifacts, create the B2
Object Lock destination, and decide whether any public endpoint exists (the
default remains none). Manila needs its approved project IDs and negative access
test. OpenStack gates need immutable disposable test-object inputs.

Magnum remains blocked on reproducible driver/provider images, exact Heat
inputs, a pinned Manila-over-NFS CSI derivative, and its workload qualification
matrix. Production remains blocked on one-member RAID repair and one-at-a-time
OSD replacement runbooks, a matched OVN NB/SB backup and restore, off-cluster
Glance/Cinder/Manila recovery, dedicated Swift capacity, and a highly available
long-term log backend decision.

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
all four controller Deployments to be Available, the GitRepository's
`SourceVerifiedCondition=True` and `sourceVerificationMode=HEAD`, and the
GitRepository and Kustomization to be Ready at the expected signed commit
revision. The SOPS identity is stable recovery state and is not regenerated
during a host or cluster rebuild.

Repository convention stays shallow: reusable implementation belongs in
`components/cloud/<component>/`; concrete resources belong in
`deployments/homelab/cloud/<cluster>/<wave>/`. Each real Kubernetes cluster gets
one Flux root when it is bootstrapped, including the separate Magnum management
cluster. A directory appears only with its first real resource.

The independent recovery destination is a private B2 bucket with compliance
Object Lock. The target policy covers undercloud and Magnum etcd, MariaDB,
RabbitMQ definitions, a writer-quiesced matched OVN NB/SB pair, and selected
tenant data. RabbitMQ message bodies are not a backup payload. Restore evidence,
not object existence alone, is the readiness condition.

A full rebuild starts from Git, PiKVM, pinned installation artifacts, the host
inventory, offline age identities, B2 recovery credentials, and retained slot
evidence. Preserved Ceph devices may be adopted only after they resolve to the
declared physical slots and match the reviewed recovery observation. No
destructive rebuild step may infer its target from a device name or serial.

## References

- [OpenStack-Helm](https://docs.openstack.org/openstack-helm/latest/) is the
  primary chart and service-layout implementation.
- [Neutron MTU guidance](https://docs.openstack.org/neutron/latest/admin/config-mtu.html)
  and the [OVN install guide](https://docs.openstack.org/neutron/latest/install/ovn/manual_install.html)
  define the Geneve allowance.
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

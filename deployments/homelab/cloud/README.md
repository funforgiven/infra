# Homelab OpenStack cloud

This directory contains the desired state for a three-node, hyperconverged
OpenStack cloud. Git records the topology, controller inputs, pinned artifacts,
and recovery configuration. It does not by itself prove that the live systems
are healthy. Workload images are pinned in the manifests that deploy them.

The platform uses Ubuntu, Kubernetes, Cilium, Flux, Rook-Ceph, and upstream
OpenStack-Helm. A separate three-node k3s management cluster runs Cluster API
and CAPO for Magnum. Self-hosted applications run outside the OpenStack control
plane in their own Magnum cluster.

## Start here

| Area | Configuration and runbook |
| --- | --- |
| Host ISO and management k3s selection | [`versions.yaml`](versions.yaml) |
| Host inventory | [`hosts/`](hosts/) and the [host runbook](hosts/README.md) |
| Physical network | [`network-inventory.yaml`](network-inventory.yaml) and the [RouterOS runbook](../routeros/README.md) |
| Kubernetes bootstrap | [`kubernetes/`](kubernetes/) and its [bootstrap notes](kubernetes/README.md) |
| Undercloud resources | [`undercloud/`](undercloud/) |
| Self-hosted services | [`services/`](services/) and its [operations guide](services/ACTIVATION.md) |
| Secrets and recovery identities | [`../../../secrets/README.md`](../../../secrets/README.md) |

Reusable implementation lives under `components/cloud/`; concrete resources
and cluster entry points live here under `deployments/`.

## Controllers

Each remote object has one controller. Import existing objects before enabling
their controller, and do not run two reconcilers for the same resource.

| Controller | Responsibility |
| --- | --- |
| PiKVM and supervised installation | Firmware, installation media, and initial OS installation |
| Ansible | Ubuntu packages, host networking, storage-slot validation, and the declared RouterOS subset |
| Omada reconciler | The declared Omada networks, profiles, ports, and wireless settings |
| Kubespray | Kubernetes, etcd, containerd, kube-vip, and the initial Cilium installation |
| Flux | Kubernetes resources after the API and CNI are healthy |
| OpenTofu | OpenStack, DNS, identity, and provider-supported external resources |
| NixOS | Standalone service hosts and their system services |
| sops-nix and Flux SOPS | Secret delivery to the NixOS controller and Kubernetes clusters |

Manual or UI-only settings are documented in the runbook for the service that
requires them, together with their backup and recovery steps. Emergency live
changes must be committed or reverted before normal reconciliation resumes.

Ordinary reconciliation must not partition disks, initialize OSDs, flash
firmware, update RouterOS, reset Kubernetes, or bootstrap Flux. Those operations
require an explicit maintenance procedure and a verified target.

## Physical topology

Every host is a Kubernetes control-plane and worker node, an OpenStack
control/compute/network node, and a Ceph failure domain.

| Host | Processor | RAM | Host storage | Ceph storage |
| --- | --- | ---: | --- | --- |
| `pecorino` | Intel Core i9-14900K | 64 GiB | 2×256 GB SATA RAID1 | 2×2 TB NVMe |
| `taleggio` | Intel Core i5-13600K | 96 GiB | 2×256 GB SATA RAID1 | 2×2 TB NVMe |
| `asiago` | AMD Ryzen 9 9900X | 64 GiB | 2×256 GB SATA RAID1 | 2×2 TB NVMe |

Disk identity is the physical `/dev/disk/by-path` connector, not a replaceable
serial number or kernel device name. Host automation discovers exactly two
interfaces using the qualified `ice` driver and bonds that group; interface
names, PCI slots, and MAC addresses are observations rather than host identity.

See the [host automation documentation](../../../components/cloud/host-automation/README.md)
for installation media, configuration, and validation commands.

## Network

Each host uses an active/fast 802.3ad `bond0` over two 25 Gb/s links with
`min-links=1`, layer-3+4 hashing, and RS-FEC. The CRS510 uses matching LAGs and a
9216-byte frame ceiling. One flow is limited to 25 Gb/s; independent flows can
use both links, and all traffic classes continue over one surviving member.

| VLAN | Purpose | MTU | Reachability |
| ---: | --- | ---: | --- |
| 20 | Hosts, Kubernetes API, and private service VIPs | 1500 | Routed through `10.21.20.1` |
| 30 | Ceph public and cluster traffic | 9000 | CRS510-local; no gateway |
| 31 | Nova live migration | 9000 | CRS510-local; no gateway |
| 32 | OVN Geneve underlay | 9000 | CRS510-local; no gateway |
| 33 | Manila NFS provider network | 1500 | CRS510-local; no gateway |
| 40 | Neutron external and floating-IP provider network | 1500 | Selected north-south traffic through the CCR2004 |
| 90 | Physical management | 1500 | Routed management only |

Ceph, migration, Geneve, and Manila traffic do not traverse the CCR2004. The
CCR's 1 Gb/s core uplink carries WAN traffic and selected north-south forwarding.
Backblaze backups are intentionally WAN-bound.

OVN tenant networks use an 8942-byte IP MTU on the 9000-byte Geneve underlay:

```text
9000 underlay - 20 outer IPv4 - 38 OVN Geneve allowance = 8942 bytes
```

The undercloud Cilium network uses native routing and a 1500-byte pod MTU.
Initial tenant clusters use a 1450-byte pod MTU over a 1500-byte VXLAN network.

### Service addresses and DNS

L2 ownership is explicit per address:

| Address | Purpose | Announcer |
| --- | --- | --- |
| `10.21.20.128` | Kubernetes API | kube-vip on `bond0.20` |
| `10.21.20.129` | Internal CoreDNS | Cilium |
| `10.21.20.130` | Private OpenStack APIs | MetalLB |
| `10.21.20.131` | Management web interfaces | MetalLB |

Cilium and MetalLB use disjoint address pools and explicit
`loadBalancerClass` values. The tested alternate path for `.129` changes
ownership in separate commits and passes through a no-owner state; see the
[service/API foundation runbook](undercloud/38-service-api-foundation/README.md).

`cloud.fahrican.com` uses split-horizon DNS. The internal CoreDNS service is
authoritative for private endpoints, and RouterOS forwards the private zone to
it. Public Cloudflare records are an explicit allow-list. DNS-01 credentials may
write ACME challenge records but do not authorize endpoint publication.

| Service | Private URL |
| --- | --- |
| ZITADEL | `https://auth.cloud.fahrican.com` |
| OpenStack Skyline | `https://dashboard.cloud.fahrican.com` |
| Grafana | `https://grafana.cloud.fahrican.com` |

Manila uses the isolated VLAN 33 provider network. `physnet-manila` maps to
`br-manila`/`bond0.33`; Ganesha VIPs use `10.21.33.20-39`, and tenant secondary
ports use `10.21.33.40-254`. The subnet has no gateway, and clients receive only
NFSv4.1 TCP 2049 access to the selected VIP.

## Storage

Rook manages six raw NVMe OSDs across the three hosts. Replicated pools use size
3, minimum size 2, host failure domains, and PG autoscaling. Separate RBD pools
serve Glance, Cinder, Nova ephemeral disks, and Cinder Backup. Manila uses a
dedicated CephFS metadata/data pair with Rook NFS-Ganesha.

Cinder Backup is a fast copy inside the Ceph failure domain, not an independent
disaster backup. Selected recovery data must also leave the cluster.

Tenant Kubernetes clusters use Cinder CSI for block storage and Manila CSI for
shared storage. They do not receive Ceph monitor addresses or cephx keys, and
Rook-on-Cinder is unsupported because it would place Ceph on volumes backed by
the same Ceph cluster.

## Backups and recovery

The independent recovery destination is a private Backblaze B2 bucket with
server-side encryption. Object Lock is disabled, so the destination is not
immutable. Upload credentials are limited to one object prefix and cannot read,
list, delete, or administer the bucket. Restore readers and age identities stay
outside the clusters as SOPS-encrypted administrator material.

Current off-cluster coverage includes:

- undercloud etcd snapshots every six hours;
- CAPI management-cluster etcd snapshots every six hours;
- a daily matched OpenStack bundle containing MariaDB and atomic OVN Northbound
  and Southbound snapshots; and
- ZITADEL PostgreSQL and its required recovery material.

B2 keeps replaced object versions for 30 days and does not expire the latest
version merely because uploads stop. A backup is usable only after an isolated
restore succeeds.

For any restore:

1. Select one object version with the offline reader and verify its recorded
   ciphertext checksum.
2. Decrypt into private temporary storage and validate the payload before
   touching a live service.
3. Restore into an isolated process or database first. Treat MariaDB, OVN NB,
   and OVN SB from one OpenStack bundle as one recovery point.
4. Quiesce writers before a supervised live restore. Reopen services in
   dependency order and rerun their health checks.
5. Remove plaintext snapshots, databases, keys, and temporary credentials when
   validation finishes.

An undercloud etcd disaster restore stops every old member, restores the chosen
snapshot with the etcd tooling pinned by the Kubernetes bootstrap, and then
rebuilds the remaining members. Flux may resume only after etcd quorum, API
encryption, the API VIP, Cilium, and the expected signed Git revision have been
verified.

The OpenStack restore procedure imports the MariaDB archive into an isolated
matching database and checks every schema. It opens both OVN database files with
the pinned OVN image and queries their global tables without forcing a schema
conversion. Only then may the matching MariaDB/NB/SB set replace live state.

## OpenStack and Magnum

OpenStack-Helm is the sole OpenStack lifecycle implementation. Its MariaDB and
RabbitMQ charts own their three-node clusters and service bootstrap jobs.
RabbitMQ queues are transport state and are rebuilt from declared service
configuration; authoritative OpenStack state is restored from MariaDB and the
matching OVN databases.

Nova uses the common named CPU model `Westmere` so guests can migrate between
the Intel and AMD hosts. Host passthrough and hand-maintained feature models are
not used. Reassess the common named-model intersection after QEMU or libvirt
upgrades.

Magnum depends on a recoverable management plane:

1. OpenStack creates three anti-affined management VMs with durable system
   volumes and an Octavia endpoint.
2. Ansible creates the HA k3s cluster.
3. Its Flux root installs CAPI, CAPO, add-on controllers, and monitoring.
4. Magnum accepts writes only while the management Kubernetes API is healthy.

Existing workload clusters continue independently during a management-plane
outage. The management kubeconfig and stable Flux/etcd recovery identities must
be preserved during a rebuild.

## Changes and upgrades

Install and recover in dependency order:

```text
hosts and network -> Kubernetes -> Flux and off-cluster backup
-> Rook/Ceph -> observability and service networking
-> MariaDB/RabbitMQ -> OpenStack core -> OpenStack services
-> CAPI management cluster -> Magnum
```

Major upgrades use separate commits and stop after each stateful layer. Before
each step, check compatibility, review the rendered change, take a fresh backup,
complete an isolated restore, run preflight checks, and document the rollback.
Do not automatically downgrade a stateful service or contract a schema while
the rollback window is open.

A full rebuild starts from Git, PiKVM, pinned installation artifacts, the host
inventory, offline age identities, and supervised B2 restore access. Never infer
a destructive disk target from `/dev/sd*`, `/dev/nvme*`, or a device serial.

## Validation

Validate the repository-owned host, network, inventory, and manifest inputs
without contacting a device:

```sh
nix build .#checks.x86_64-linux.cloud-configuration \
  --no-link --accept-flake-config
```

Use the focused runbooks for operations that contact or mutate systems:

- [Ubuntu host automation](../../../components/cloud/host-automation/README.md)
- [RouterOS and Omada automation](../../../components/cloud/network-automation/README.md)
- [RouterOS topology and recovery](../routeros/README.md)
- [Kubernetes bootstrap](kubernetes/README.md)
- [Service/API L2 transitions](undercloud/38-service-api-foundation/README.md)
- [Self-hosted service operations](services/ACTIVATION.md)
- [AWS mail operations and recovery](../../../components/cloud/services/mail-aws/README.md)

## Accepted risks

- Physical boot with either OS disk absent has not been tested. Both EFI trees
  and both RAID1 members are checked, but independent firmware/OS boot remains
  unverified.
- The hosts use consumer CPUs, non-ECC RAM, and non-PLP NVMe. Each host has one
  dual-port 25 GbE adapter; the fabric has one CRS510; automated UPS shutdown is
  not configured.
- The B2 recovery bucket has no Object Lock.
- Metrics and logs use the Ceph cluster they monitor, so a complete Ceph outage
  also removes historical observability data until Ceph recovers.

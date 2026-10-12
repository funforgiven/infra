# Target architecture and decisions

Three NixOS machines run one flake-pinned K3s cluster with three embedded-etcd
servers. Every server also schedules applications and is a Ceph failure domain.
No management Kubernetes cluster, guest Kubernetes cluster, VM compute cloud,
tenant control plane, or cloud infrastructure controller remains.

K3s is selected for the NixOS-native module, embedded-etcd lifecycle and lower
host maintenance burden. Kubernetes is pinned by `flake.lock`, currently
1.36.4+k3s1. Traefik, ServiceLB, local-path storage, bundled network policy and
the bundled Helm controller are disabled. Flux owns application/Helm lifecycles.
The first server initializes etcd; the other two join through the API VIP.

Cilium 1.20.2 supplies the primary VXLAN pod network and eBPF service routing.
Kube-proxy is disabled. Its official OCI chart is pinned by manifest digest;
the matching upstream CRDs are vendored and hash checked. Flux owns the Helm
release after the identical configuration is installed during CNI bootstrap.
Standard Kubernetes NetworkPolicies retain Matrix and NetBird allowlists.
Forge and backup jobs use Cilium policies; explicit deny rules isolate restore
and export helpers. The general Forge policy excludes its API-only backup and
offline export pods so additive policy evaluation cannot broaden their access.

MetalLB announces retained IPv4 VIPs on the management and services VLANs.
It preserves the existing `externalTrafficPolicy: Local` client-address
requirement. Cilium L2 announcements are incompatible with that setting, so
their replacement requires a separately qualified BGP or service-routing
design. Envoy Gateway remains for its current listener, admission and routing
configuration. Cilium's Gateway API, ingress, L2 announcement and BGP controllers
are disabled, and it does not allocate LoadBalancer addresses. Its unused L7
proxy/Envoy and Hubble relay/UI are disabled to limit additional workloads.

The host-level keepalived service owns only the Kubernetes API VIP and does
not require CNI or Flux to bootstrap. Multus/macvlan remains for IoT and the
UniFi guest's secondary VLAN attachment. `cni.exclusive: false` keeps Cilium
from renaming the Multus configuration. Socket load balancing stays in the
host namespace so the pod's primary TC datapath sees service traffic alongside
the separate secondary network. NixOS supplies cgroup v2 at `/sys/fs/cgroup`;
Cilium mounts bpffs and uses the existing cgroup mount. VXLAN uses UDP 8472
between node management addresses. LoadBalancer processing attaches to
`bond0.20` and `bond0.40`, excluding the Ceph and IoT interfaces.

Policy permits for in-cluster HTTPS VIPs also select the corresponding managed
gateway pods on translated port 10443; VIP CIDRs alone cannot identify those
backends after Cilium service translation. Physical qualification must cover
DNS, cross-host traffic, client-address preservation, failover, allowed and
denied application flows, and the independent IoT interface before app release.

Rook/Ceph remains on the six existing NVMe connectors. One replicated RBD pool
and one replicated CephFS filesystem replace the cloud storage pools and NFS
provider machinery. The default migration path restores independent backups
into fresh direct-CSI PVCs; retaining OSD disks is not itself a cluster restore.
Replica count remains three, minimum two, across three hosts. Ceph resources
remain realistic; removing compute-cloud overhead is the principal RAM saving.

The two SATA disks hold declarative mirrored ESP and root MD arrays. Disk
selection is by inventoried physical connector, not guessed kernel names.
Ceph disks are absent from disko. The boot filesystem uses metadata 1.0 so both
members contain a firmware-readable FAT filesystem and removable EFI boot path.
Physical boot with either SATA member absent must be qualified during cutover.

Flux Kustomizations use semantic folders, explicit `dependsOn` and readiness
checks. Stateful applications are restored before their reconciliation is
released. Off-cluster DNS, identity configuration, AWS mail infrastructure and
NetBird policy retain declarative OpenTofu configuration operated from the
workstation; they do not require an in-cluster OpenTofu operator.

UniFi OS Server requires its supported Ubuntu environment. A single small
KubeVirt VM preserves this service and its IP, controlled through Kubernetes;
the three physical machines remain NixOS. Native Windows/macOS CI and their
image, broker and virtualization plumbing are removed by the owner's request.
Linux CI, Nix package cache, Forgejo packages, signing and recovery stay.

Primary references, checked during preparation:

- https://docs.k3s.io/datastore/ha-embedded
- https://docs.k3s.io/networking/basic-network-options
- https://docs.cilium.io/en/stable/installation/k3s/
- https://docs.cilium.io/en/stable/network/l2-announcements/
- https://docs.cilium.io/en/stable/helm-reference/
- https://metallb.io/usage/#traffic-policies
- https://github.com/nix-community/disko/blob/master/example/boot-raid1.nix
- https://rook.io/docs/rook/latest-release/Storage-Configuration/Ceph-CSI/ceph-csi-drivers/

These are architectural decisions made for this branch. Hardware qualification,
backup evidence and the actual installation remain future maintenance work.

The exact K3s v1.36.4+k3s1 source was checked: `pkg/executor/embed/embed.go`
sets embedded CNI paths only when flannel is enabled. With flannel disabled,
this branch uses standard containerd CNI paths `/opt/cni/bin` and
`/etc/cni/net.d` for Cilium, Multus and the pinned static secondary plugins.
The existing router/switch VLAN tables stay in `deployments/homelab/network`;
unused cloud-internal VLANs can be retired only after the migration, according
to the runbook. NixOS hosts create VLANs 20, 30, 40 and 50.

Read-only source inspection captured service runtime values, ACME account,
management certificate and independent provider states into the operator-only
encrypted `secrets/migration-state.sops.yaml`. No live resources were changed.
Refresh this snapshot before cutover; it is not a database or volume backup.

Home Assistant's former services address, `10.21.40.120`, becomes a dedicated
HTTP-only MetalLB Service on port 8123. The internal Service retains Zigbee UI
and metrics ports for gateway/monitoring access. LAN access is restricted to
the trusted VLAN and the workstation's administrative WireGuard address;
the IoT attachment keeps its separate static macvlan address and firewall.

The new pod CIDR is `10.100.0.0/16`; app reverse-proxy trust and Forge gateway
client authorization are updated from the old workload pod range. Home
Assistant's restored HTTP storage migrates that known proxy range while
preserving custom/user settings. Native runner IPs `.125/.126` and the old
workload API `.121` remain outside the target MetalLB pools. UniFi probes use
its retained `.127` services NIC rather than the former Neutron subnet.

Envoy's mail-admin connection now leaves through a cluster node's management
address. RouterOS and the independent mail guest's WireGuard/nginx allowlists
therefore authorize exactly the three inventoried node IPs to backend TCP 8080.
The HTTPS gateway still admits only the existing trusted LAN/admin VPN clients.
Applying this coordinated routing change belongs to the future runbook; neither
the router nor AWS guest has been changed during preparation.

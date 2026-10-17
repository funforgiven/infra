# Architecture

Three NixOS machines run one flake-pinned K3s cluster with three embedded-etcd
servers. Every server also schedules applications and is a Ceph failure domain.

K3s is used for the NixOS-native module, embedded-etcd lifecycle and lower
host maintenance burden. Kubernetes is pinned by `flake.lock`, currently
1.36.4+k3s1. Traefik, ServiceLB, local-path storage, bundled network policy and
the bundled Helm controller are disabled. Flux owns application/Helm lifecycles.
The first server initializes etcd; the other two join through the API VIP.

Cilium 1.20.2 supplies the primary VXLAN pod network and eBPF service routing.
Kube-proxy is disabled. Its official OCI chart is pinned by manifest digest;
the matching upstream CRDs are vendored and hash checked. Flux owns the Helm
release after the identical configuration is installed during CNI bootstrap.
Standard Kubernetes NetworkPolicies enforce Matrix and NetBird allowlists.
Forge and backup jobs use Cilium policies; deny rules isolate restore and
export helpers. The general Forge policy excludes its API-only backup and
offline export pods so additive policy evaluation cannot broaden their access.

MetalLB announces IPv4 VIPs on the management and services VLANs. It keeps
the `externalTrafficPolicy: Local` client-address behavior. Cilium L2
announcements are incompatible with that setting, so replacing MetalLB needs a
separate BGP or service-routing design. Envoy Gateway handles listeners,
admission and routing. Cilium's Gateway API, ingress, L2 announcement and BGP
controllers are disabled, and it does not allocate LoadBalancer addresses. Its
unused L7 proxy/Envoy and Hubble relay/UI are disabled to limit workloads.

The host-level keepalived service owns only the Kubernetes API VIP and does
not require CNI or Flux to bootstrap. Multus/macvlan provides IoT and the
UniFi guest's secondary VLAN attachment. `cni.exclusive: false` keeps Cilium
from renaming the Multus configuration. Socket load balancing stays in the
host namespace so the pod's primary TC datapath sees service traffic alongside
the separate secondary network. NixOS supplies cgroup v2 at `/sys/fs/cgroup`;
Cilium mounts bpffs and uses the host cgroup mount. VXLAN uses UDP 8472
between node management addresses. LoadBalancer processing attaches to
`bond0.20` and `bond0.40`, excluding the Ceph and IoT interfaces.

Policy permits for in-cluster HTTPS VIPs also select the corresponding managed
gateway pods on translated port 10443; VIP CIDRs alone cannot identify those
backends after Cilium service translation.

Rook-Ceph uses the six NVMe disks, two per host. One replicated RBD pool
(`ceph-block`) and one replicated CephFS filesystem provide storage, with
replica count three, minimum two, across three hosts. Applications restore from
off-cluster backups into fresh PVCs; keeping OSD disks alone is not a cluster
restore. Rook stores monitor state under `/var/lib/rook` on the SATA roots.

The two SATA disks hold declarative mirrored ESP and root MD arrays. Disk
selection is by inventoried physical connector, not kernel names. Ceph disks
are absent from disko. The boot filesystem uses metadata 1.0 so both members
contain a firmware-readable FAT filesystem and removable EFI boot path.

Flux Kustomizations use semantic folders, `dependsOn` and readiness checks.
The recovery overlay holds stateful applications until their data is restored.
Off-cluster DNS, identity configuration, AWS mail infrastructure and NetBird
policy are OpenTofu roots run from the workstation; there is no in-cluster
OpenTofu operator.

UniFi OS Server requires its supported Ubuntu environment. A single small
KubeVirt VM runs it with a fixed IP, controlled through Kubernetes; the three
physical machines are NixOS. There are no native Windows/macOS CI runners.
Linux CI, Nix package cache, Forgejo packages, signing and recovery run in the
cluster.

K3s v1.36.4+k3s1 `pkg/executor/embed/embed.go` sets embedded CNI paths only
when flannel is enabled. With flannel disabled, Cilium, Multus and the pinned
static secondary plugins use the standard containerd CNI paths `/opt/cni/bin`
and `/etc/cni/net.d`. Recheck this when upgrading K3s. Router/switch VLAN
tables live in `deployments/homelab/network`. NixOS hosts create VLANs 20, 30,
40 and 50.

Home Assistant uses `10.21.40.120`, a dedicated HTTP-only MetalLB Service on
port 8123. The internal Service carries Zigbee UI and metrics ports for
gateway/monitoring access. LAN access is restricted to the trusted VLAN and the
workstation's administrative WireGuard address; the IoT attachment keeps its
separate static macvlan address and firewall.

Pod CIDR is `10.100.0.0/16`; app reverse-proxy trust and Forge gateway client
authorization use that range. UniFi probes use its `.127` services NIC.

Envoy's mail-admin connection leaves through a cluster node's management
address. RouterOS and the AWS mail host's WireGuard/nginx allowlists therefore
authorize exactly the three inventoried node IPs to backend TCP 8080. The HTTPS
gateway admits only trusted LAN/admin VPN clients.

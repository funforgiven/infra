# Architecture

One workstation (`parmigiano`), three NixOS servers running one K3s cluster
(`pecorino`, `taleggio`, `asiago`), a NixOS mail host on AWS, and the physical
network. Configuration describes what exists; this document records who owns
each piece and why it is built this way. Versions, addresses and sizes live in
the files referenced here, not in prose.

## Ownership

Every resource has exactly one declarative owner. The repository has no
reconcilers of its own beyond the API adapters listed at the end.

| Owner | Scope | Where |
| --- | --- | --- |
| NixOS / Home Manager (flake) | workstation, cluster hosts (disks, network, K3s, host backups), mail host | `components/nix/`, `deployments/homelab/hosts/` |
| Flux (Kustomize, Helm) | everything inside the cluster | `deployments/homelab/cluster/` |
| OpenTofu, run from the workstation | ZITADEL, Cloudflare DNS, NetBird policy, AWS mail and IAM, the Backblaze bucket | `components/homelab/providers/` |
| Ansible / Omada OpenAPI | RouterOS router and switch, Omada switch | `components/homelab/network-automation/`, `deployments/homelab/network/` |
| SOPS | every secret value, encrypted beside its consumer | see [secrets](../secrets/README.md) |

`deployments/homelab/hosts/inventory.json` is the host inventory (addresses,
disks, API VIP). Nix reads it directly. Kubernetes manifests that cannot read
it (CoreDNS zone, Rook monitor addresses, the Cilium API endpoint) keep literal
copies that the manifest validator checks against it.

## Hosts and cluster

K3s is used for its NixOS module, embedded etcd and low maintenance. All three
servers are control-plane, etcd, workload and Ceph failure domains. The first
initializes etcd; the others join through the API VIP, which host-level
keepalived owns so that it needs neither CNI nor Flux. Flannel, kube-proxy,
Traefik, ServiceLB, local-path and the embedded Helm controller are disabled:
Flux owns every add-on.

Boot disks are two mirrored SATA disks per host, selected by physical connector
rather than kernel name; the ESP uses metadata 1.0 so firmware can read either
member. The NVMe disks are not in disko: Rook-Ceph owns them (one replicated RBD
pool and one CephFS, size 3/min 2 across hosts). Keeping OSD disks is not a
restore strategy; data comes back from off-cluster backups.

The three hosts share one SOPS age identity, delivered at install time. That
keeps installation simple but means one compromised host exposes the others'
host secrets; per-host recipients would fix it at the cost of re-encrypting.

## Networking

Cilium is the CNI in kube-proxy-replacement mode (VXLAN between management
addresses). Because Flux needs a CNI, Cilium is installed once by hand during a
cluster build with the HelmRelease's own chart digest and values, and Flux
adopts the release. Cilium's Gateway API, L2 announcements, BGP, L7 proxy and
Hubble UI are off.

MetalLB announces LoadBalancer VIPs because it keeps
`externalTrafficPolicy: Local` client addresses, which Cilium L2 announcements
do not support; replacing it needs a BGP design. Envoy Gateway terminates every
HTTP listener. Network policy permits for in-cluster HTTPS VIPs must also select
the gateway pods on their translated port, because a VIP CIDR alone no longer
identifies the backend after service translation.

Multus adds macvlan attachments on the IoT VLAN for home automation (Matter,
Thread and Zigbee need L2 discovery). `cni.exclusive: false` stops Cilium from
renaming the Multus configuration. With flannel disabled, K3s uses the standard
`/opt/cni/bin` and `/etc/cni/net.d` paths; recheck this on K3s upgrades.
Restore radio pairing keys and the Thread dataset before any IoT workload
reconnects, and stop pods using a secondary attachment before removing Multus
or a NetworkAttachmentDefinition.

Private services resolve only inside the LAN and NetBird. The workstation's
WireGuard admin tunnel stays outside NetBird so the network can be repaired
when NetBird is down ([network](network.md)).

## Flux

`deployments/homelab/cluster/waves/stages.yaml` is the dependency graph: plain
Flux Kustomizations with `dependsOn`. Shared settings and health rules are
patched in once by `waves/kustomization.yaml`. Health means "serving with one
node lost": replicated workloads may run one replica short, single-replica
workloads must be up. Dependencies exist only where a stage needs another's
CRDs or services; in particular nothing depends on `observability`, because it
is restored from backup and must not block the restore tooling.

Stages labelled `homelab.fahrican.com/recovery=hold` are suspended by the
`deployments/homelab/recovery` overlay so Ceph and stateful apps do not start
on empty volumes during a rebuild ([recovery](recovery.md)).

Namespaces are declared centrally in `cluster/namespaces.yaml`, which carries
Pod Security levels and the labels gateways use to admit routes.

## Data and backups

- **PostgreSQL** runs on CloudNativePG. Databases that matter (identity,
  NetBird, Matrix) archive WAL and base backups to Backblaze with the Barman
  Cloud plugin, giving point-in-time recovery. Recomputable databases rely on
  volume backups.
- **Volumes** are backed up by Velero to Backblaze. Application hooks exist
  only where a crash-consistent copy is not enough (a game save, the Matrix
  relay's crypto store).
- **etcd and host identities** are backed up by each host with Restic to its
  own Backblaze prefix and key, which cluster workloads cannot reach.
- **Restore drills** run in-cluster into isolated `*-restore` namespaces with
  deny-all network policy, so a recovered copy can never talk to production.

Details and procedures: [backups](../deployments/homelab/cluster/infrastructure/backups/README.md).

## External providers

OpenTofu roots run from the workstation; there is no in-cluster Terraform
controller, so the cluster can be rebuilt without them and vice versa. State is
committed in Git, encrypted by OpenTofu itself, and the passphrase is SOPS
ciphertext; the `nix run .#tofu` wrapper supplies it ([providers](../components/homelab/providers/README.md)).
ZITADEL client secrets are the one place a provider output feeds cluster
Secrets: `identity-credentials` copies them into the consuming SOPS files.

The mail host is a single NixOS instance on AWS (Stalwart, RDS, S3), replaced
in place rather than recreated; it reaches the LAN-only admin backend over a
WireGuard peer that may only reach the three node addresses
([mail](../components/homelab/services/mail-aws/README.md)).

UniFi OS Server only supports Ubuntu, so it runs as one KubeVirt VM; its guest
scripts are generated from `components/homelab/services/unifi`.

## Validation

`nix flake check` builds every host and runs the repository checks. The
manifest check renders every Kustomize entrypoint and HelmRelease with charts
and API schemas fetched by Nix from pins, so a chart bump without a pin bump,
a schema violation, a Flux graph error or a broken repository policy fails
offline and without decrypting anything.

## Remaining imperative code

Retained only where no declarative owner exists:

- Application logic: the Matrix alert relay, Forgejo runner launcher and cache
  gateway, media import policy, mail operations, desktop hardware integration
  (audio MIDI routing, OBSBOT camera, Home Assistant MIDI controls).
- API adapters without a provider: the Omada switch reconciler, Forgejo
  account/token enrollment, the NetBird credential rotation, `identity-credentials`.
- RouterOS is driven by Ansible over SSH CLI rather than its API because the
  playbook shares rule tables it does not fully own ([network](network.md)).
- Restore drills and their verifiers.

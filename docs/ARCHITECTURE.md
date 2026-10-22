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

Code that runs in the cluster sits beside its manifests and is shipped with
`configMapGenerator`; code shared between namespaces, built into images or used
by operators lives under `components/homelab/services/` with its tests.

Namespaces are declared in `cluster/namespaces.yaml`, which carries Pod
Security levels and the labels gateways use to admit routes. Moving a namespace
between Flux Kustomizations is done in two releases (identical unprunable
copies first, then the old copy removed) so neither garbage-collects it; the
`databases` stage still holds such copies of `cnpg-system`, `netbird` and
`netbird-routing`.

## Data and backups

- **PostgreSQL** runs on CloudNativePG. Databases that matter (identity,
  NetBird, Matrix) archive WAL and base backups to Backblaze with the Barman
  Cloud plugin, giving point-in-time recovery. Recomputable databases rely on
  volume backups.
- **Volumes** are backed up by Velero's CSI snapshot data mover to Backblaze.
  Application hooks exist only where a crash-consistent copy is not enough (a
  Factorio save, the Matrix relay's crypto store and canary). The CephFS media
  library is the one filesystem backup, because exporting a CephFS snapshot
  clones the whole volume.
- **etcd and host identities** are backed up by each host with Restic to its
  own Backblaze prefix and key, which cluster workloads cannot reach.
- **Restore drills** run monthly in-cluster into isolated `*-restore`
  namespaces with deny-all network policy, so a recovered copy can never talk
  to production: one Velero drill for volumes and one CloudNativePG recovery
  test per archived database. The mail host has its own drill on AWS.

Details and procedures: [backups](../deployments/homelab/cluster/infrastructure/backups/README.md).

## External providers

OpenTofu roots run from the workstation; there is no in-cluster Terraform
controller, so the cluster can be rebuilt without them and vice versa. State is
committed in Git, encrypted by OpenTofu itself, and the passphrase is SOPS
ciphertext; the `nix run .#tofu` wrapper supplies it ([providers](../components/homelab/providers/README.md)).
ZITADEL client secrets are the one provider output that feeds cluster
Secrets: `identity-credentials` copies them into the consuming SOPS files.
Other operator tools that mint credentials (Forgejo enrollment, NetBird token
rotation, Matrix bot enrollment) write their results straight into the
consumer's SOPS file the same way.

The mail host is a single NixOS instance on AWS (Stalwart, RDS, S3), replaced
in place rather than recreated; it reaches the LAN-only admin backend over a
WireGuard peer that may only reach the three node addresses
([mail](../components/homelab/services/mail-aws/README.md)).

UniFi OS Server only supports Ubuntu, so it runs as one KubeVirt VM. Its guest
scripts are shipped as a ConfigMap disk from `components/homelab/services/unifi`;
its credentials are still pushed over SSH by `enroll-service-host-secrets`
because a KubeVirt Secret disk would need new ciphertext and only refreshes on
VM restart.

## Validation

`nix flake check` builds every host and runs the repository checks. The
manifest check renders every Kustomize entrypoint and HelmRelease with charts
and API schemas fetched by Nix from pins, so a chart bump without a pin bump,
a schema violation, a Flux graph error or a broken repository policy fails
offline and without decrypting anything.

## Remaining imperative code

Retained only where no declarative owner exists:

- Application logic: the Matrix alert relay and its external probe, the
  Forgejo runner launcher, job registration and cache gateway, media import
  policy, Stalwart bootstrap and mail operations on the mail host, the UniFi
  guest's install, backup and health scripts, game-server entrypoints, small
  metrics exporters for services only reachable on loopback, and desktop
  hardware integration (audio MIDI routing, OBSBOT camera, Home Assistant MIDI
  controls, Niri chat layout).
- API adapters without a provider: the Omada switch reconciler, in-cluster
  AudioMuse and Navidrome account/plugin reconcilers, pinned Home Assistant
  component installs, Forgejo account/token enrollment, NetBird credential
  rotation and route copies (`render_routes.py`; Gateway API cannot vary
  admission per parent), image publishing, `identity-credentials`,
  `enroll-service-host-secrets`, and the RØDECaster Home Assistant automation
  installer (its webhook IDs exist only in workstation SOPS).
- RouterOS is driven by Ansible over SSH CLI rather than its API because the
  playbook shares rule tables it does not fully own ([network](network.md)).
- Restore drills, their verifiers and the manifest validator.

## Known gaps

Improvements that need decryption, new ciphertext or live verification, so
they are recorded rather than done blind:

- Synapse and MAS configuration, including non-secret settings, is one SOPS
  value; splitting it into a plain ConfigMap plus secret files needs the
  decrypted original.
- The three cluster hosts share one age identity; per-host recipients need
  each host's key in `.sops.yaml` and re-encryption of the host secrets.
- UniFi guest credentials (SSH push) and the RØDECaster automation webhook IDs
  (workstation-only SOPS) would move into Kubernetes Secrets once that
  ciphertext is created.
- Alert delivery is still dual Telegram/Matrix until Matrix delivery is
  verified live ([rollout](rollout.md)).
- RouterOS could move to its REST API once the playbook owns whole rule tables
  ([network](network.md)).

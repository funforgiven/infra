# NixOS physical servers and AWS mail

`deployments/homelab/hosts/` declares pecorino, taleggio and asiago as NixOS/K3s
servers with embedded etcd, dedicated SOPS recipient, 25 Gb/s LACP/VLAN
networking and mirrored-SATA disko. Their six NVMe disks are outside disko and
belong to Rook-Ceph. Home automation runs as Kubernetes pods; UniFi runs in a
supported Ubuntu guest managed by KubeVirt. Mail runs on a separate aarch64 AWS
NixOS host.

Each server sends K3s etcd snapshots to the Restic prefix (`initialize=false`;
never initialize over the existing repository). Restore needs the snapshot, K3s
token, TLS/bootstrap state and host identities.

`enroll-service-host-secrets` delivers the UniFi backup/monitoring profiles.
Read [secret recovery](../../../secrets/README.md) before changing credentials.

## Hardware identity

| Host | CPU | Motherboard | Installed RAM |
| --- | --- | --- | --- |
| `taleggio` | Core i5-13600K | MSI PRO Z690-A WIFI (MS-7D25), revision 2.0 | 96 GiB: 2 × 48 GiB DDR5 at 5600 MT/s |
| `asiago` | Ryzen 9 9900X | MSI PRO B650M-A WIFI (MS-7D77), revision 1.0 | 64 GiB: 2 × 32 GiB DDR5 at 4800 MT/s |
| `pecorino` (recorded) | Core i9-14900K | Needs live verification | 64 GiB; DIMM layout and speed need live verification |

Taleggio and Asiago match their live SSH hostnames, CPU and DMI data. Their
DIMMs occupy A2/B2; the speeds above are firmware-reported configured speeds.
Taleggio uses `F5-6400J3239F48G` modules and BIOS `A.H0`; Asiago uses
`F5-6000J3040G32G` modules and BIOS `1.R5`. Pecorino's CPU comes from the
recorded inventory and its RAM capacity from its last Kubernetes report;
neither substitutes for a fresh hardware check.

Taleggio and Asiago each have two Kingston `SKC600256G` SATA boot disks and
two `SKC3000D2048G` NVMe Ceph disks, plus a dual-port Intel 25 Gb/s NIC
(`8086:159b`, driver `ice`). Both enumerate integrated graphics without an
NVIDIA GPU.

Their live LACP partners confirm Taleggio on CRS510 ports `sfp28-3/4` and
Asiago on `sfp28-5/6`, matching the [network map](../../../deployments/homelab/routeros/README.md#physical-map).
Use the hostname and hardware together to identify a chassis; link lights and
switch port labels alone do not establish which server is attached. The
[PiKVM map](../../../deployments/homelab/pikvm/README.md#two-switch-chain)
lists console ports.

## Reinstall a host / rebuild the cluster

Boot an installer through [PiKVM](../../../deployments/homelab/pikvm/README.md)
and match the host's SATA serials and connectors against
`deployments/homelab/hosts/inventory.json` before formatting. Only the two SATA
members are in disko; never wipe the NVMe OSD disks while Ceph holds data.

Prepare an owner-only `extra-files` directory outside Git:

| Destination | Encrypted source | Mode |
| --- | --- | --- |
| `/var/lib/sops-nix/key.txt` | `secrets/kubernetes.yaml`, `cluster.host_age_identity` | 0600; parents 0700 |
| `/etc/ssh/ssh_host_ed25519_key` | `deployments/homelab/hosts/secrets.sops.yaml`, `hosts.<host>.ssh_host_ed25519_key` | 0600 |

```sh
umask 077
EXTRA=/private/path/pecorino-extra-files
install -d -m 0700 "$EXTRA/var/lib/sops-nix" "$EXTRA/etc/ssh"
sops decrypt --extract '["cluster"]["host_age_identity"]' secrets/kubernetes.yaml \
  > "$EXTRA/var/lib/sops-nix/key.txt"
sops decrypt --extract '["hosts"]["pecorino"]["ssh_host_ed25519_key"]' \
  deployments/homelab/hosts/secrets.sops.yaml > "$EXTRA/etc/ssh/ssh_host_ed25519_key"
ssh-keygen -y -f "$EXTRA/etc/ssh/ssh_host_ed25519_key" | ssh-keygen -lf -
```

Check the fingerprint against `deployments/homelab/ssh-host-keys.json`. Do not
copy the personal or Flux age key onto the hosts. Install, which runs disko and
destroys the selected SATA contents:

```sh
nix run --inputs-from . nixos-anywhere -- \
  --flake .#pecorino --target-host root@INSTALLER_ADDRESS \
  --extra-files "$EXTRA"
```

Do not use `--copy-host-keys`; those are temporary installer keys. Remove the
extra-files directory afterwards. A reinstalled host rejoins etcd through the
API VIP `10.21.20.128` with the K3s token from its secrets. Restore one host at
a time and keep etcd and Ceph quorum.

### Rebuilding the whole cluster

After all three hosts are up, copy the admin kubeconfig from the first server
and point it at `https://10.21.20.128:6443`. Flux cannot start without a CNI,
so install Cilium first with the same chart and values as its HelmRelease:

```sh
kubectl apply -f deployments/homelab/cluster/infrastructure/cilium/vendor/
helm pull oci://quay.io/cilium/charts/cilium --version 1.20.2 --destination /tmp
helm upgrade --install cilium /tmp/cilium-1.20.2.tgz --namespace kube-system \
  --values deployments/homelab/cluster/infrastructure/cilium/values.yaml --wait --timeout 20m
kubectl wait nodes --all --for=condition=Ready --timeout=20m
```

Check the chart archive SHA-256 against
`deployments/homelab/validation/sources.json`. Flux adopts the release later.

Install Flux, deliver `cluster.flux_age_identity` from `secrets/kubernetes.yaml`
as the `flux-system/sops-age` Secret through stdin, then bootstrap the recovery
overlay instead of `gotk-sync.yaml`:

```sh
kubectl apply -f deployments/homelab/cluster/bootstrap/flux/gotk-components.yaml
kubectl -n flux-system wait deployment/source-controller --for=condition=Available --timeout=10m
kubectl apply -k deployments/homelab/recovery
```

The recovery overlay points the root `flux-system` Kustomization at itself and
suspends Ceph, observability and stateful apps. To release a held stage, first
suspend the root Kustomization; otherwise its next reconciliation sets
`suspend: true` again. Restore each app from Velero or its native backup before
releasing it. Once everything runs, `kubectl apply -k deployments/homelab/cluster`
returns the root to the normal path.

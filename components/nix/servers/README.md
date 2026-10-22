# NixOS physical servers and AWS mail

`deployments/homelab/hosts/` declares pecorino, taleggio and asiago as NixOS/K3s
servers with embedded etcd, one shared host age identity, 25 Gb/s LACP/VLAN
networking and mirrored-SATA disko. Their six NVMe disks are outside disko and
belong to Rook-Ceph. Home automation runs as Kubernetes pods; UniFi runs in a
supported Ubuntu guest managed by KubeVirt. Mail runs on a separate aarch64 AWS
NixOS host.

Each server sends its K3s etcd snapshot, token, TLS/credential state, host age
identity and SSH host key to a Restic repository in Backblaze
(`deployments/homelab/hosts/backup.nix`), whose B2 key cannot be used by
cluster workloads. Restore needs the snapshot, K3s token, TLS/bootstrap state
and host identities.

`enroll-service-host-secrets` delivers the UniFi backup/monitoring profiles.
Read [secret recovery](../../../secrets/README.md) before changing credentials.

## Hardware identity

| Host | CPU | Motherboard | Installed RAM |
| --- | --- | --- | --- |
| `taleggio` | Core i5-13600K | MSI PRO Z690-A WIFI (MS-7D25), revision 2.0 | 96 GiB: 2 × 48 GiB DDR5 at 5600 MT/s |
| `asiago` | Ryzen 9 9900X | MSI PRO B650M-A WIFI (MS-7D77), revision 1.0 | 64 GiB: 2 × 32 GiB DDR5 at 4800 MT/s |
| `pecorino` | Core i9-14900K | MSI MAG Z790 TOMAHAWK MAX WIFI (MS-7E25), revision 2.0 | 64 GiB: 4 × 16 GiB DDR5 at 4000 MT/s |

All three match their live SSH hostnames, CPU and DMI data. The DIMMs in
Taleggio and Asiago occupy A2/B2; Pecorino uses all four slots. The speeds
above are firmware-reported configured speeds.
Taleggio uses `F5-6400J3239F48G` modules and BIOS `A.H0`; Asiago uses
`F5-6000J3040G32G` modules and BIOS `1.R5`. Pecorino uses
`F5-6000J3040F16G` modules and BIOS `A.80`.

Pecorino uses automatic memory frequency and timings, with XMP and Memory
Fast Boot disabled. After CMOS resets or RAM changes, check that Secure Boot
remains disabled for the installed GRUB loader.

Taleggio and Asiago each have two Kingston `SKC600256G` SATA boot disks and
two `SKC3000D2048G` NVMe Ceph disks, plus a dual-port Intel 25 Gb/s NIC
(`8086:159b`, driver `ice`). Both enumerate integrated graphics without an
NVIDIA GPU.

Their live LACP partners confirm Taleggio on CRS510 ports `sfp28-3/4` and
Asiago on `sfp28-5/6`, matching the [cabling map](../../../docs/network.md#cabling).
Use the hostname and hardware together to identify a chassis; link lights and
switch port labels alone do not establish which server is attached. The
[PiKVM section](../../../docs/network.md#pikvm) lists console ports.

## Reinstall a host / rebuild the cluster

Boot an installer through [PiKVM](../../../docs/network.md#pikvm)
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
API VIP (`cluster.apiVip` in the inventory) with the K3s token from its secrets. Restore one host at
a time and keep etcd and Ceph quorum.

To rebuild the whole cluster, see [disaster recovery](../../../docs/recovery.md).

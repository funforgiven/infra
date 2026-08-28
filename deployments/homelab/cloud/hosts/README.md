# Physical cloud hosts

The inventory contains three installed Ubuntu hosts. Each machine is a
Kubernetes control plane, etcd member, and worker, and carries the OpenStack
control-plane, compute, network, and storage workloads assigned by the cluster
manifests.

| Host | Management address | CPU |
| --- | --- | --- |
| `pecorino` | `10.21.20.10` | Intel Core i9-14900K, 32 threads |
| `taleggio` | `10.21.20.11` | Intel Core i5-13600K, 20 threads |
| `asiago` | `10.21.20.12` | AMD Ryzen 9 9900X, 24 threads |

[`inventory.yml`](inventory.yml) assigns the cluster roles.
[`group_vars/all.yml`](group_vars/all.yml) defines the shared bond, VLAN, MTU,
DNS, and SSH settings. Files under [`host_vars`](host_vars) contain only the
per-host addresses, physical disk connectors, CPU-specific virtualization
settings, and controller-side console-password path.

## Replacement and rebuild requirements

Before installing or returning a host to service, check that its inventory
still identifies:

- exactly two 25 GbE interfaces using the `ice` driver;
- two SATA OS disks and two NVMe Ceph disks by `/dev/disk/by-path` connector;
- the expected VLAN addresses and Intel or AMD IOMMU/KVM settings;
- its sops-nix console and sudo password file.

Connector paths are the disk identity. Serial numbers, `/dev/sd*`,
`/dev/nvme*`, interface names, MAC addresses, and PCI slots are observations and
must not be copied into the inventory as desired state. The automation discovers
the two `ice` interfaces and builds `bond0` from that driver-matched pair.

Run the reusable Ansible preflight and network checks after installation or a
hardware change. Commands and installation-media instructions are in the
[host automation guide](../../../../components/cloud/host-automation/README.md).

## Known risk

The automated preflight checks both EFI partitions and both members of each OS
RAID1 array. Booting each machine with either OS disk physically absent has not
been tested; keep remote console access available for disk replacement and boot
recovery.

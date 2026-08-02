# Physical cloud hosts

All three machines are installed members of `cloud_hosts` and pass the automated
host and all-direction network qualification. Failure of each individual LACP
member also preserves every required path. Independent-OS-disk boot tests are a
deferred resilience exercise and do not block Kubernetes bootstrap.

| Host | State | Management | CPU |
| --- | --- | --- | --- |
| `pecorino` | automated-qualified | `10.21.20.10` | Intel Core i9-14900K, 32 threads |
| `taleggio` | automated-qualified | `10.21.20.11` | Intel Core i5-13600K, 20 threads |
| `asiago` | automated-qualified | `10.21.20.12` | AMD Ryzen 9 9900X, 24 threads |

For every replacement or rebuild, verify:

- exactly two 25 GbE interfaces using the qualified `ice` driver;
- two SATA OS and two NVMe Ceph `/dev/disk/by-path` connector paths;
- host VLAN addresses and the architecture-specific IOMMU/KVM settings;
- its sops-nix runtime path for the console/sudo password.

The disk paths identify physical connectors. Current serials and `/dev/sd*` or
`/dev/nvme*` names are observations, not desired state. Network interface names
and PCI slots are also observations: the role discovers exactly two `ice`
interfaces and Netplan bonds that driver-matched group.
See the reusable role and commands in
[`components/cloud/host-automation`](../../../../components/cloud/host-automation/README.md).

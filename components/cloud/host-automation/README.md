# Cloud host automation

This small Ansible project owns only unavoidable Ubuntu host state:

- packages, chrony, and key-only SSH;
- KVM/IOMMU modules and boot parameters;
- the two-port LACP bond and VLAN interfaces;
- health checks for CPU, disks, RAID1, EFI, KVM, IOMMU, and the 25 GbE links;
- synchronization of the installer-created backup EFI partition.

It does not install Kubernetes, Flux, Ceph, OpenStack, or Magnum. It never
partitions, formats, wipes, repairs, or enrolls a disk. Those workflows belong
to the component that owns them when that component is actually introduced.

## Installation media

Build one host-specific image at a time with the reusable builder. The local
Ansible renderer derives identity, network, and credential paths from the
`cloud_hosts` inventory. The builder verifies the official ISO against
`versions.yaml`, embeds only a SHA-512 password hash, and preserves hybrid
BIOS/UEFI boot metadata:

```sh
nix develop --accept-flake-config
components/cloud/host-automation/build-autoinstall-iso.sh \
  asiago ~/Downloads/ubuntu-24.04.4-live-server-amd64.iso \
  /tmp/ubuntu-24.04.4-asiago-autoinstall.iso
```

`pecorino`, `taleggio`, and `asiago` use the same inventory-rendered template.
An optional fourth argument overrides the inventory password file, which is
useful only for controlled recovery. The preflight aborts before storage
changes unless it sees a UEFI boot, exactly two interfaces using the qualified
NIC driver, two 250-270 GB SATA SSDs, and two 1.9-2.1 TB NVMe SSDs. It mirrors
only the SATA pair and has no storage action for the Ceph NVMes.

Rendered data stays in a private temporary directory and is removed when the
builder exits. The generated mode-0600 ISO is refused inside the repository and
powers the host off when installation finishes.

## Usage

Run from this directory so `ansible.cfg` supplies the inventory and role path:

```sh
nix develop --accept-flake-config
cd components/cloud/host-automation
ansible-inventory --graph
ansible-playbook playbooks/configure-hosts.yml --limit taleggio --check --diff
ansible-playbook playbooks/configure-hosts.yml --limit taleggio --diff
ansible-playbook playbooks/preflight.yml --limit taleggio
ansible-playbook playbooks/qualify-network.yml --limit taleggio
```

The configure play is serial and targets only `cloud_hosts`. Keep PiKVM open
for a network change. The role disables cloud-init network rendering, removes
other Netplan YAML files, and requires `99-openstack-host.yaml` to be the sole
source before applying it. If GRUB parameters change, reboot the host
separately and rerun preflight.

The `ubuntu` account authenticates to SSH only by key. Its per-host console and
sudo password is read from a sops-nix runtime file on the controller; inventory
contains only that file path. Password and root SSH login remain disabled.
The installed public key matches the existing SOPS-managed Git/automation key;
Ansible and the `ssh pecorino`, `ssh taleggio`, and `ssh asiago` aliases use its
`0400` runtime file with `IdentitiesOnly=yes`. Host identity is pinned in the
shared homelab known-hosts file.

## Storage and boot

Inventory identifies disks by `/dev/disk/by-path` connector paths, not current
serial numbers or kernel-order names. Replacing a compatible disk in the same
connector therefore does not change desired state. The preflight verifies two
SATA OS disks, two NVMe Ceph disks, and two healthy `[2/2] [UU]` RAID1 arrays.

Ubuntu's installer creates one EFI partition on each OS disk but mounts only
one. The role finds the other inventoried `part1`, mounts it at
`/boot/efi-secondary`, and mirrors the EFI tree after package transactions and
at boot. It does not create or format an ESP.

## Network

Netplan renders `bond0` as fast 802.3ad LACP with `min-links=1` and a
layer-3+4 hash. It renders addressed VLANs 20 and 30–32 plus unnumbered
`bond0.40` for the Open vSwitch external-provider bridge. VLAN 33 is reserved
in the architecture and is added during the later Manila wave. The role
discovers exactly two interfaces using the
qualified `ice` driver and bonds Netplan's driver-matched group; kernel names,
PCI slots, and permanent MAC addresses are not inventory identity.

The qualification play is read-only. It checks both members at 25 GbE/full
duplex with active RS-FEC, the LACP state, and the only default route on VLAN
20. With more than one installed host it also checks 1500-byte management and
9000-byte east-west paths in every direction.

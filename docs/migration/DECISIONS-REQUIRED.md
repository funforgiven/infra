# Owner input for the future cutover

Software choices are implemented in this branch: NixOS on the three physical
hosts, embedded-etcd K3s, Calico, MetalLB, Multus, direct Rook-Ceph CSI and
KubeVirt for the existing supported UniFi OS guest. Windows/macOS runners are
excluded at the owner's request. Downtime is acceptable; parallel old/new
production clusters are unnecessary. No live changes are authorized by this
preparation goal.

| Input | Why the operator needs it | Proposed default |
| --- | --- | --- |
| Off-server staging location and available capacity | All irreplaceable bytes must survive wiping the old operating systems and creating the new Ceph cluster. B2 backups alone need restore qualification and may take substantial time to download. The media claim reserves 1 TiB; actual allocated sizes are not used-byte measurements. | An external disk/NAS attached to the workstation, plus B2 for the independently verified archive. Record free space and measured used bytes before scheduling. |
| PiKVM address, credentials and host-to-port mapping | Firmware access must survive loss of cluster DNS, ZITADEL and VPN. Neither reachability nor virtual USB boot has been qualified yet. | One V4 Plus with official Switch, HDMI and USB to all three; independent power/network. See CONSOLE-ACCESS.md. |
| Physical recovery availability without ATX | A powered-off or completely frozen motherboard cannot be recovered through keyboard input. | Owner available to press a power/reset button during installation. |
| Cutover start time | The operator must stop writers, take the final verified backups and release existing VIP ownership before reinstalling hosts. | One downtime window after every backup/restore and disk-identity gate passes. |

These are inputs for execution, not requests to change the architecture.
Installation also requires recorded proof of backup completeness, a successful
test restore, current provider state and the physical disk serial/connector
checks in the runbook. They are execution gates, not completed preparation
tests. Keeping six existing OSD disks does not preserve the old Ceph cluster
without its monitor state, credentials and metadata; fresh Ceph plus verified
restore is the default migration path.

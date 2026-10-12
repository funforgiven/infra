# Secondary IoT networking

Calico owns the primary pod network. Multus v4.3.1-thick adds secondary macvlan
attachments for home automation. Its upstream release manifest is vendored,
image digest pinned, NAD RBAC narrowed to reads and resources bounded through
Kustomize. It keeps the host mounts and privileges needed for CNI delegation.

NixOS provides checksum-pinned CNI plugins in `/opt/cni/bin` and the primary CNI
configuration directory `/etc/cni/net.d`. It creates the unnumbered VLAN-50
`iot0` interface on each physical server. The three hosts carry the IoT label;
there is no guest NIC attachment, Neutron port or in-cluster host reconciler.
RouterOS/Omada retain the physical VLAN contract. Prepare that network before
releasing the home automation stage.

Home Assistant and its colocated services retain `10.21.50.10`; the separate
OTBR retains `.50.11`. The Zigbee and Thread radios stay `.50.20`/`.50.21`.
Restore pairing keys, PAN/network identity and the Thread operational dataset
before connecting either workload. Macvlan delivers packets by destination MAC,
allowing OTBR to route traffic toward its IPv6 mesh. Disabling IPv6 on the
unnumbered host interface does not disable the pod's secondary IPv6 network.

Verify ARP, IPv6 multicast, mDNS/device discovery, radio TCP 6638 and actual
Zigbee/Matter/Thread commands from restored pods. The exact NAD and pod-local
firewall policy are in [home automation](../../apps/home-automation/README.md).
Check isolation and all device identities before normal schedules resume.

Stop pods using secondary attachments before removing Multus or a NAD. Remove
their network annotations before restarting without that attachment. Preserve
the primary Calico/kube-proxy firewall state during recovery. The full data and
cutover procedures are in [DATA-MIGRATION.md](../../../../../docs/migration/DATA-MIGRATION.md)
and [RUNBOOK.md](../../../../../docs/migration/RUNBOOK.md).

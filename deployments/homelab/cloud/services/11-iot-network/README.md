# IoT pod networking

Multus adds a secondary macvlan bridge interface to automation pods. Calico remains
the primary CNI. `vendor/multus.yaml` is the upstream Apache-2.0 deployment from
[multus-cni v4.3.1](https://github.com/k8snetworkplumbingwg/multus-cni/blob/v4.3.1/deployments/multus-daemonset-thick.yml),
with the image pinned, its NAD RBAC narrowed to reads and its memory budget
adjusted through Kustomize. The controller must retain its host mounts and
privileges to delegate CNI calls; application containers do not receive them.

`iot-node-network` runs only on nodes enrolled by `reconcile-iot.py`. It installs
the macvlan/static/tuning plugins (and ipvlan for removal of old attachments) from the checksum-verified CNI v1.9.1
release, configures the dedicated unnumbered NIC and drops input to the worker
on that interface. It neither changes the primary NIC nor flushes existing
Calico/kube-proxy firewall tables. Network attachments and pod-local firewall
rules are in [home automation](../25-home-automation/README.md).

Apply physical network state first using the existing Omada/RouterOS owners
and `components/cloud/host-automation/playbooks/configure-network.yml`. The
OpenStack compute chart adds `physnet-iot:br-iot` over `bond0.50`. OpenTofu then
creates `services-iot`; the services reconciler attaches worker NICs and labels
them. This Flux layer prepares the nodes before the automation StatefulSet.

Check all prepared workers, then test IPv4 ARP and IPv6 multicast from an
attached pod. Never remove Multus while pods with secondary networks remain.
For removal, stop those pods first, remove their network annotations and only
then retire this layer. Do not flush the node's global nftables or iptables
rules during rollback.

The Thread border router routes packets addressed to mesh nodes behind `net1`.
IPvlan demultiplexes by destination IP and cannot deliver those routed packets
to this border-router namespace. Macvlan delivers by Ethernet destination and
allows OTBR to route the advertised IPv6 mesh prefix. Neutron IoT port security
is disabled to carry these additional MACs; primary tenant ports stay protected.

For an ipvlan-to-macvlan migration, first install both plugins on every prepared
worker. Suspend only the home-automation Flux Kustomization, stop both automation
StatefulSets and any temporary ipvlan probes, update both NADs, then resume one
instance of each StatefulSet. A parent NIC cannot host both driver types at once.
Keep the ipvlan binary until all old attachments have been removed by CNI DEL.

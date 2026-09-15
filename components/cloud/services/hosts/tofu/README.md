# Automation network and retired service hosts

This OpenTofu root creates the `services-iot` flat provider network on
`physnet-iot` for the services project. It has no DHCP, subnet, router or
Neutron IPv6 advertisements. The existing physical IoT LAN owns addressing;
Multus attaches only the automation pods. `iot_network_id` is its sole output.

The owner authorized removal of the empty standalone Home Assistant. Explicit
`removed { lifecycle { destroy = true } }` blocks retire its VM, NixOS and HAOS
boot volumes, dedicated ports, security groups and rules. They also preserve
the earlier Hermes retirement declarations. No backup or restore of the empty
legacy appliance is required. Glance image publication for HAOS is retired.

The services-hosts Terraform controller follows services foundation and precedes
the services-cluster reconciler, which attaches an unnumbered IoT NIC to each
worker. The physical switches, host VLAN and OVS bridge must be ready first.
See the [automation runbook](../../../../../deployments/homelab/cloud/services/25-home-automation/README.md)
for deployment, networking and recovery.

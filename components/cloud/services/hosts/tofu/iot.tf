# A layer-2 attachment to the physical IoT VLAN. No Neutron router, DHCP or
# IPv6 RA agent participates; the LAN router and Thread border routers own L3.
resource "openstack_networking_network_v2" "iot" {
  name                  = "services-iot"
  description           = "Automation-only L2 access to physical VLAN 50"
  admin_state_up        = true
  port_security_enabled = false
  mtu                   = 1500
  tags                  = local.tags

  segments {
    network_type     = "flat"
    physical_network = "physnet-iot"
  }
}

output "iot_network_id" {
  value = openstack_networking_network_v2.iot.id
}

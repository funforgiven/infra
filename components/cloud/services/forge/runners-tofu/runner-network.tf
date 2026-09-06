locals {
  # The exact complement of private, link-local, loopback, multicast, CGNAT,
  # benchmark and documentation ranges. No default allow-all egress rule.
  internet_ipv4 = jsondecode(file("${path.module}/internet-ipv4.json"))
  web_egress    = { for pair in setproduct(local.internet_ipv4, [80, 443]) : "${pair[0]}:${pair[1]}" => { cidr = pair[0], port = pair[1] } }
  private_egress = {
    forgejo_https = { cidr = "10.21.40.122/32", protocol = "tcp", port = 443 }
    forgejo_ssh   = { cidr = "10.21.40.122/32", protocol = "tcp", port = 2222 }
    dns_udp       = { cidr = "10.21.40.1/32", protocol = "udp", port = 53 }
    dns_tcp       = { cidr = "10.21.40.1/32", protocol = "tcp", port = 53 }
    ntp           = { cidr = "162.159.200.1/32", protocol = "udp", port = 123 }
    ntp_backup    = { cidr = "162.159.200.123/32", protocol = "udp", port = 123 }
    dhcp          = { cidr = "255.255.255.255/32", protocol = "udp", port = 67 }
    dhcp_renew    = { cidr = "192.168.81.0/24", protocol = "udp", port = 67 }
  }
}

resource "openstack_networking_secgroup_v2" "runner" {
  provider             = openstack.ci
  name                 = "forge-runner-isolation"
  delete_default_rules = true
}
resource "openstack_networking_secgroup_rule_v2" "runner_web" {
  provider          = openstack.ci
  for_each          = local.web_egress
  security_group_id = openstack_networking_secgroup_v2.runner.id
  direction         = "egress"
  ethertype         = "IPv4"
  protocol          = "tcp"
  remote_ip_prefix  = each.value.cidr
  port_range_min    = each.value.port
  port_range_max    = each.value.port
}
resource "openstack_networking_secgroup_rule_v2" "runner_private" {
  provider          = openstack.ci
  for_each          = local.private_egress
  security_group_id = openstack_networking_secgroup_v2.runner.id
  direction         = "egress"
  ethertype         = "IPv4"
  protocol          = each.value.protocol
  remote_ip_prefix  = each.value.cidr
  port_range_min    = each.value.port
  port_range_max    = each.value.port
}
resource "openstack_networking_secgroup_rule_v2" "runner_management" {
  provider          = openstack.ci
  for_each          = { for pair in setproduct(local.operators, [22, 3389]) : "${pair[0]}:${pair[1]}" => { cidr = pair[0], port = pair[1] } }
  security_group_id = openstack_networking_secgroup_v2.runner.id
  direction         = "ingress"
  ethertype         = "IPv4"
  protocol          = "tcp"
  remote_ip_prefix  = each.value.cidr
  port_range_min    = each.value.port
  port_range_max    = each.value.port
}
resource "openstack_networking_secgroup_rule_v2" "runner_monitoring" {
  provider          = openstack.ci
  for_each          = toset(["9100", "9182", "9252"])
  security_group_id = openstack_networking_secgroup_v2.runner.id
  direction         = "ingress"
  ethertype         = "IPv4"
  protocol          = "tcp"
  remote_ip_prefix  = "10.21.40.154/32"
  port_range_min    = tonumber(each.value)
  port_range_max    = tonumber(each.value)
}

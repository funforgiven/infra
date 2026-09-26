terraform {
  required_version = ">= 1.12.1, < 1.13.0"
  required_providers {
    openstack = {
      source  = "terraform-provider-openstack/openstack"
      version = "= 3.4.0"
    }
  }
}
provider "openstack" {
  tenant_id           = ""
  tenant_name         = "services"
  project_domain_name = "Default"
}
locals {
  inputs = jsondecode(file("${path.module}/../inputs.json"))
  # Separate controller and AP identities; the old EAP static address is not
  # reused until its replacement's Ethernet MAC has been verified.
  address     = "192.168.80.12"
  floating_ip = "10.21.40.127"
  ingress = {
    admin_ssh    = { protocol = "tcp", port = 22, cidr = "10.21.10.20/32" }
    vpn_ssh      = { protocol = "tcp", port = 22, cidr = "10.21.91.0/24" }
    admin_setup  = { protocol = "tcp", port = 11443, cidr = "10.21.10.20/32" }
    vpn_setup    = { protocol = "tcp", port = 11443, cidr = "10.21.91.0/24" }
    gateway      = { protocol = "tcp", port = 8443, cidr = "192.168.80.0/24" }
    node_metrics = { protocol = "tcp", port = 9100, cidr = "192.168.80.0/24" }
    ap_metrics   = { protocol = "tcp", port = 9130, cidr = "192.168.80.0/24" }
    inform       = { protocol = "tcp", port = 8080, cidr = "10.21.90.6/32" }
    stun         = { protocol = "udp", port = 3478, cidr = "10.21.90.6/32" }
  }
  scripts = ["bootstrap.sh", "backup.sh", "renew-tls.sh", "health.sh"]
  cloud_config = {
    hostname         = "unifi"
    manage_etc_hosts = true
    ssh_pwauth       = false
    disable_root     = true
    users = [{
      name                = "ubuntu"
      groups              = ["sudo", "adm"]
      shell               = "/bin/bash"
      lock_passwd         = true
      sudo                = ["ALL=(ALL) NOPASSWD:ALL"]
      ssh_authorized_keys = [trimspace(file("${path.module}/../../../../../secrets/github-ssh-key.pub"))]
    }]
    package_update = true
    packages       = ["podman", "slirp4netns", "passt", "uidmap", "curl", "ca-certificates", "openssl", "nginx", "restic", "prometheus-node-exporter", "qemu-guest-agent", "unattended-upgrades"]
    swap           = { filename = "/swapfile", size = 2147483648 }
    write_files = concat([
      for name in local.scripts : {
        path        = "/usr/local/lib/unifi/${name}"
        permissions = "0755"
        encoding    = "b64"
        content     = filebase64("${path.module}/../${name}")
      }
      ], [
      {
        path        = "/usr/local/lib/unifi/inputs.json"
        permissions = "0644"
        content     = jsonencode(local.inputs)
      },
      {
        path        = "/etc/ssh/sshd_config.d/00-unifi.conf"
        permissions = "0644"
        content     = "PasswordAuthentication no\nKbdInteractiveAuthentication no\nPermitRootLogin no\n"
      }
    ])
    runcmd = [["/usr/local/lib/unifi/bootstrap.sh"]]
  }
}
data "openstack_networking_network_v2" "services" { name = "services" }
data "openstack_networking_subnet_v2" "services" { name = "services-v4" }
data "openstack_images_image_v2" "ubuntu" {
  name = "Ubuntu 24.04 Noble 20260801 amd64"
}
data "openstack_compute_flavor_v2" "unifi" { name = "services.master" }
resource "openstack_networking_secgroup_v2" "unifi" {
  name                 = "unifi-ap-controller"
  description          = "AP-only controller: private gateway, monitoring, admin and inform/STUN"
  delete_default_rules = true
}
resource "openstack_networking_secgroup_rule_v2" "ingress" {
  for_each          = local.ingress
  security_group_id = openstack_networking_secgroup_v2.unifi.id
  direction         = "ingress"
  ethertype         = "IPv4"
  protocol          = each.value.protocol
  port_range_min    = each.value.port
  port_range_max    = each.value.port
  remote_ip_prefix  = each.value.cidr
}
# OS packages, firmware and the prefix-scoped encrypted backup use outbound
# connections. Routing/firewall policy remains on the CCR, never in UniFi.
resource "openstack_networking_secgroup_rule_v2" "egress" {
  security_group_id = openstack_networking_secgroup_v2.unifi.id
  direction         = "egress"
  ethertype         = "IPv4"
}
resource "openstack_networking_port_v2" "unifi" {
  name               = "unifi"
  network_id         = data.openstack_networking_network_v2.services.id
  security_group_ids = [openstack_networking_secgroup_v2.unifi.id]
  fixed_ip {
    subnet_id  = data.openstack_networking_subnet_v2.services.id
    ip_address = local.address
  }
}
resource "openstack_networking_floatingip_v2" "unifi" {
  pool    = "public"
  address = local.floating_ip
  port_id = openstack_networking_port_v2.unifi.id
}
resource "openstack_blockstorage_volume_v3" "unifi" {
  name     = "unifi-root"
  size     = 64
  image_id = data.openstack_images_image_v2.ubuntu.id
  lifecycle {
    prevent_destroy = true
    ignore_changes  = [image_id]
  }
}
resource "openstack_compute_instance_v2" "unifi" {
  name                = "unifi"
  flavor_id           = data.openstack_compute_flavor_v2.unifi.id
  user_data           = "#cloud-config\n${yamlencode(local.cloud_config)}"
  config_drive        = true
  stop_before_destroy = true
  metadata            = { purpose = "unifi-access-points-only" }
  block_device {
    uuid                  = openstack_blockstorage_volume_v3.unifi.id
    source_type           = "volume"
    destination_type      = "volume"
    boot_index            = 0
    delete_on_termination = false
  }
  network { port = openstack_networking_port_v2.unifi.id }
  lifecycle {
    prevent_destroy = true
    # Day-two updates use the same checked-in scripts over pinned SSH, not VM
    # replacement or a cloud-init rerun on a stateful controller.
    ignore_changes = [user_data]
  }
}
output "unifi_address" { value = local.floating_ip }

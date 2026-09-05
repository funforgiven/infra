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
  tenant_name         = "gitlab"
  project_domain_name = "Default"
}

variable "image_revision" {
  type        = string
  description = "Full signed revision of promoted NixOS GitLab/runner images"
  validation {
    condition     = can(regex("^[0-9a-f]{40}$", var.image_revision))
    error_message = "Promote a signed full Git revision before provisioning."
  }
}

locals {
  operators = toset(["10.21.10.0/24", "10.21.91.0/24"])
}

data "openstack_networking_network_v2" "gitlab" { name = "gitlab" }
data "openstack_networking_subnet_v2" "gitlab" { name = "gitlab-v4" }

data "openstack_compute_flavor_v2" "gitlab" { name = "gitlab" }

data "openstack_images_image_v2" "gitlab" {
  name       = "nixos-gitlab-${substr(var.image_revision, 0, 12)}"
  properties = { image_role = "gitlab", image_source_revision = var.image_revision }
}

resource "openstack_networking_secgroup_v2" "gitlab" {
  name                 = "gitlab-data"
  delete_default_rules = true
}

resource "openstack_networking_secgroup_rule_v2" "gitlab_ssh" {
  for_each          = local.operators
  security_group_id = openstack_networking_secgroup_v2.gitlab.id
  direction         = "ingress"
  ethertype         = "IPv4"
  protocol          = "tcp"
  port_range_min    = 22
  port_range_max    = 22
  remote_ip_prefix  = each.value
}

resource "openstack_networking_secgroup_rule_v2" "gitlab_origin" {
  for_each          = toset(["5432", "6379", "8075"])
  security_group_id = openstack_networking_secgroup_v2.gitlab.id
  direction         = "ingress"
  ethertype         = "IPv4"
  protocol          = "tcp"
  port_range_min    = tonumber(each.value)
  port_range_max    = tonumber(each.value)
  remote_ip_prefix  = "192.168.82.0/24"
}

resource "openstack_networking_secgroup_rule_v2" "gitlab_egress" {
  security_group_id = openstack_networking_secgroup_v2.gitlab.id
  direction         = "egress"
  ethertype         = "IPv4"
  remote_ip_prefix  = "0.0.0.0/0"
}

resource "openstack_networking_port_v2" "gitlab" {
  name               = "gitlab"
  network_id         = data.openstack_networking_network_v2.gitlab.id
  security_group_ids = [openstack_networking_secgroup_v2.gitlab.id]
  fixed_ip {
    subnet_id  = data.openstack_networking_subnet_v2.gitlab.id
    ip_address = "192.168.82.10"
  }
  lifecycle { prevent_destroy = true }
}

resource "openstack_networking_floatingip_v2" "gitlab" {
  pool    = "public"
  address = "10.21.40.128"
  port_id = openstack_networking_port_v2.gitlab.id
}

resource "openstack_blockstorage_volume_v3" "gitlab" {
  name     = "gitlab-root"
  size     = 300
  image_id = data.openstack_images_image_v2.gitlab.id
  lifecycle { prevent_destroy = true }
}

resource "openstack_compute_instance_v2" "gitlab" {
  name                = "gitlab"
  flavor_id           = data.openstack_compute_flavor_v2.gitlab.id
  config_drive        = true
  stop_before_destroy = true
  block_device {
    uuid                  = openstack_blockstorage_volume_v3.gitlab.id
    source_type           = "volume"
    destination_type      = "volume"
    boot_index            = 0
    delete_on_termination = false
  }
  network { port = openstack_networking_port_v2.gitlab.id }
  lifecycle { prevent_destroy = true }
}

output "gitlab_management_address" { value = openstack_networking_floatingip_v2.gitlab.address }

resource "openstack_networking_secgroup_rule_v2" "gitlab_monitoring" {
  security_group_id = openstack_networking_secgroup_v2.gitlab.id
  direction         = "ingress"
  ethertype         = "IPv4"
  protocol          = "tcp"
  port_range_min    = 9100
  port_range_max    = 9100
  remote_ip_prefix  = "10.21.40.154/32"
}

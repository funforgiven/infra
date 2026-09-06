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
  alias               = "ci"
  tenant_id           = ""
  tenant_name         = "forge-ci"
  project_domain_name = "Default"
}

variable "macos_image_revision" {
  type        = string
  description = "Full signed revision of the promoted NixOS Quickemu host image"
  validation {
    condition     = can(regex("^[0-9a-f]{40}$", var.macos_image_revision))
    error_message = "Promote a signed full Git revision before provisioning."
  }
}

locals {
  operators = toset(["10.21.10.0/24", "10.21.91.0/24"])
  runners = {
    windows = { address = "192.168.81.11", floating_ip = "10.21.40.125" }
    macos   = { address = "192.168.81.12", floating_ip = "10.21.40.126" }
  }
}

data "openstack_networking_network_v2" "ci" {
  provider = openstack.ci
  name     = "forge-ci"
}

data "openstack_networking_subnet_v2" "ci" {
  provider = openstack.ci
  name     = "forge-ci-v4"
}

data "openstack_images_image_v2" "macos" {
  provider = openstack.ci
  name     = "nixos-forge-macos-${substr(var.macos_image_revision, 0, 12)}"
  properties = {
    image_role            = "forge-macos"
    image_source_revision = var.macos_image_revision
  }
}

data "openstack_compute_flavor_v2" "macos" {
  provider = openstack.ci
  name     = "forge-macos"
}

# Windows VMs are created and destroyed by the external job broker. Terraform
# owns only their fixed isolated port, never a reusable Windows job disk.
resource "openstack_networking_port_v2" "runner" {
  provider           = openstack.ci
  for_each           = local.runners
  name               = "forge-${each.key}"
  network_id         = data.openstack_networking_network_v2.ci.id
  security_group_ids = concat([openstack_networking_secgroup_v2.runner.id], each.key == "macos" ? [openstack_networking_secgroup_v2.macos_broker.id] : [])
  fixed_ip {
    subnet_id  = data.openstack_networking_subnet_v2.ci.id
    ip_address = each.value.address
  }
}

resource "openstack_networking_floatingip_v2" "runner" {
  provider = openstack.ci
  for_each = local.runners
  pool     = "public"
  address  = each.value.floating_ip
  port_id  = openstack_networking_port_v2.runner[each.key].id
}

resource "openstack_blockstorage_volume_v3" "macos" {
  provider = openstack.ci
  name     = "forge-macos-root"
  size     = 240
  image_id = data.openstack_images_image_v2.macos.id
  lifecycle { prevent_destroy = true }
}

resource "openstack_compute_instance_v2" "macos" {
  provider            = openstack.ci
  name                = "forge-macos"
  flavor_id           = data.openstack_compute_flavor_v2.macos.id
  availability_zone   = "nova:taleggio"
  stop_before_destroy = true
  metadata = {
    purpose = "forgejo-actions-macos-hypervisor"
  }
  block_device {
    uuid                  = openstack_blockstorage_volume_v3.macos.id
    source_type           = "volume"
    destination_type      = "volume"
    boot_index            = 0
    delete_on_termination = false
  }
  network { port = openstack_networking_port_v2.runner["macos"].id }
  lifecycle { prevent_destroy = true }
}

output "runner_management_addresses" {
  value = { for name, ip in openstack_networking_floatingip_v2.runner : name => ip.address }
}

output "windows_port_id" {
  value = openstack_networking_port_v2.runner["windows"].id
}

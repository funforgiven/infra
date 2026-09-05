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
  tenant_name         = "gitlab-ci"
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

variable "windows_image_name" {
  type        = string
  description = "Qualified Windows 11 Pro image, UEFI Secure Boot and TPM 2.0"
  validation {
    condition     = can(regex("^windows-11-pro-[0-9a-f]{64}$", var.windows_image_name))
    error_message = "Use the immutable Windows 11 Pro image name containing its SHA256."
  }
}

locals {
  operators = toset(["10.21.10.0/24", "10.21.91.0/24"])
  runners = {
    windows = { address = "192.168.81.11", floating_ip = "10.21.40.125", disk = 240 }
    macos   = { address = "192.168.81.12", floating_ip = "10.21.40.126", disk = 240 }
  }
}

data "openstack_networking_subnet_v2" "ci" {
  provider = openstack.ci
  name     = "gitlab-ci-v4"
}

data "openstack_images_image_v2" "runner" {
  provider   = openstack.ci
  for_each   = toset(["macos"])
  name       = "nixos-gitlab-${each.key}-${substr(var.image_revision, 0, 12)}"
  properties = { image_role = "gitlab-${each.key}", image_source_revision = var.image_revision }
}

data "openstack_images_image_v2" "windows" {
  provider = openstack.ci
  name     = var.windows_image_name
  properties = {
    image_role       = "gitlab-windows"
    os_distro        = "windows"
    windows_edition  = "Windows 11 Pro"
    hw_firmware_type = "uefi"
    os_secure_boot   = "required"
    hw_tpm_version   = "2.0"
    hw_tpm_model     = "tpm-crb"
    hw_machine_type  = "q35"
  }
}

resource "openstack_networking_port_v2" "runner" {
  provider           = openstack.ci
  for_each           = local.runners
  name               = "gitlab-${each.key}"
  network_id         = data.openstack_networking_network_v2.ci.id
  security_group_ids = [openstack_networking_secgroup_v2.runner.id]
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

resource "openstack_blockstorage_volume_v3" "runner" {
  provider = openstack.ci
  for_each = local.runners
  name     = "gitlab-${each.key}-root"
  size     = each.value.disk
  image_id = each.key == "windows" ? data.openstack_images_image_v2.windows.id : data.openstack_images_image_v2.runner[each.key].id
  lifecycle { prevent_destroy = true }
}

resource "openstack_compute_instance_v2" "runner" {
  provider  = openstack.ci
  for_each  = local.runners
  name      = "gitlab-${each.key}"
  flavor_id = data.openstack_compute_flavor_v2.runner[each.key].id
  # macOS needs Intel VMX and AVX2; keep it on the qualified nested host.
  availability_zone   = each.key == "macos" ? "nova:pecorino" : null
  config_drive        = true
  stop_before_destroy = true
  block_device {
    uuid                  = openstack_blockstorage_volume_v3.runner[each.key].id
    source_type           = "volume"
    destination_type      = "volume"
    boot_index            = 0
    delete_on_termination = false
  }
  network { port = openstack_networking_port_v2.runner[each.key].id }
  lifecycle { prevent_destroy = true }
}

output "runner_management_addresses" { value = { for name, ip in openstack_networking_floatingip_v2.runner : name => ip.address } }

data "openstack_networking_network_v2" "ci" {
  provider = openstack.ci
  name     = "gitlab-ci"
}

data "openstack_compute_flavor_v2" "runner" {
  provider = openstack.ci
  for_each = local.runners
  name     = "gitlab-${each.key}"
}

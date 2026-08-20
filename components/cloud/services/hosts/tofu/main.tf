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
  # The controller receives the existing administrative credential Secret,
  # which may itself be scoped to the admin project. Explicitly request the
  # services project without persisting or minting another credential.
  tenant_id           = ""
  tenant_name         = "services"
  project_domain_name = "Default"
}

variable "image_revision" {
  description = "Full signed Git revision promoted into Glance"
  type        = string

  validation {
    condition     = can(regex("^[0-9a-f]{40}$", var.image_revision))
    error_message = "image_revision must be a full lowercase 40-character Git commit."
  }
}

locals {
  image_revision_short  = substr(var.image_revision, 0, 12)
  tags                  = ["managed-by-opentofu", "platform-services"]
  trusted_operator_cidr = "10.21.10.0/24"
}

data "openstack_networking_network_v2" "services" {
  name = "services"
}

data "openstack_networking_subnet_v2" "services" {
  name       = "services-v4"
  network_id = data.openstack_networking_network_v2.services.id
}

data "openstack_networking_network_v2" "public" {
  name     = "public"
  external = true
}

data "openstack_networking_subnet_v2" "public" {
  name       = "public-v4"
  network_id = data.openstack_networking_network_v2.public.id
}

data "openstack_compute_flavor_v2" "services" {
  name = "services.worker"
}

data "openstack_images_image_v2" "hermes" {
  name = "nixos-hermes-${local.image_revision_short}"

  properties = {
    image_role            = "hermes"
    image_source_revision = var.image_revision
  }
}

data "openstack_images_image_v2" "home_assistant" {
  name = "nixos-home-assistant-${local.image_revision_short}"

  properties = {
    image_role            = "home-assistant"
    image_source_revision = var.image_revision
  }
}

resource "openstack_networking_secgroup_v2" "service_ssh" {
  name        = "service-ssh"
  description = "SSH and diagnostics from the trusted operator LAN"
  tags        = local.tags
}

resource "openstack_networking_secgroup_rule_v2" "service_ssh" {
  direction         = "ingress"
  ethertype         = "IPv4"
  protocol          = "tcp"
  port_range_min    = 22
  port_range_max    = 22
  remote_ip_prefix  = local.trusted_operator_cidr
  security_group_id = openstack_networking_secgroup_v2.service_ssh.id
}

resource "openstack_networking_secgroup_rule_v2" "service_icmp" {
  direction         = "ingress"
  ethertype         = "IPv4"
  protocol          = "icmp"
  remote_ip_prefix  = local.trusted_operator_cidr
  security_group_id = openstack_networking_secgroup_v2.service_ssh.id
}

# Temporary recovery path used only to deploy the networkd fix to the existing
# Home Assistant boot volume. Remove after direct provider-LAN SSH is healthy.
resource "openstack_networking_secgroup_rule_v2" "home_assistant_recovery_ssh" {
  direction         = "ingress"
  ethertype         = "IPv4"
  protocol          = "tcp"
  port_range_min    = 22
  port_range_max    = 22
  remote_ip_prefix  = "192.168.80.11/32"
  security_group_id = openstack_networking_secgroup_v2.service_ssh.id
}

resource "openstack_networking_secgroup_rule_v2" "service_node_exporter" {
  direction         = "ingress"
  ethertype         = "IPv4"
  protocol          = "tcp"
  port_range_min    = 9100
  port_range_max    = 9100
  remote_ip_prefix  = "192.168.80.0/24"
  security_group_id = openstack_networking_secgroup_v2.service_ssh.id
}

resource "openstack_networking_secgroup_v2" "home_assistant_private" {
  name        = "home-assistant-private"
  description = "Home Assistant ingress from services workloads"
  tags        = local.tags
}

resource "openstack_networking_secgroup_rule_v2" "home_assistant_private_http" {
  direction         = "ingress"
  ethertype         = "IPv4"
  protocol          = "tcp"
  port_range_min    = 8123
  port_range_max    = 8123
  remote_ip_prefix  = "192.168.80.0/24"
  security_group_id = openstack_networking_secgroup_v2.home_assistant_private.id
}

resource "openstack_networking_secgroup_v2" "home_assistant_provider" {
  name        = "home-assistant-provider"
  description = "Home Assistant UI and discovery from the trusted operator LAN"
  tags        = local.tags
}

resource "openstack_networking_secgroup_rule_v2" "home_assistant_provider_ssh" {
  direction         = "ingress"
  ethertype         = "IPv4"
  protocol          = "tcp"
  port_range_min    = 22
  port_range_max    = 22
  remote_ip_prefix  = local.trusted_operator_cidr
  security_group_id = openstack_networking_secgroup_v2.home_assistant_provider.id
}

resource "openstack_networking_secgroup_rule_v2" "home_assistant_provider_http" {
  direction         = "ingress"
  ethertype         = "IPv4"
  protocol          = "tcp"
  port_range_min    = 8123
  port_range_max    = 8123
  remote_ip_prefix  = local.trusted_operator_cidr
  security_group_id = openstack_networking_secgroup_v2.home_assistant_provider.id
}

resource "openstack_networking_secgroup_rule_v2" "home_assistant_provider_mdns" {
  direction         = "ingress"
  ethertype         = "IPv4"
  protocol          = "udp"
  port_range_min    = 5353
  port_range_max    = 5353
  remote_ip_prefix  = local.trusted_operator_cidr
  security_group_id = openstack_networking_secgroup_v2.home_assistant_provider.id
}

resource "openstack_networking_secgroup_rule_v2" "home_assistant_provider_ssdp" {
  direction         = "ingress"
  ethertype         = "IPv4"
  protocol          = "udp"
  port_range_min    = 1900
  port_range_max    = 1900
  remote_ip_prefix  = local.trusted_operator_cidr
  security_group_id = openstack_networking_secgroup_v2.home_assistant_provider.id
}

resource "openstack_networking_secgroup_rule_v2" "home_assistant_provider_icmp" {
  direction         = "ingress"
  ethertype         = "IPv4"
  protocol          = "icmp"
  remote_ip_prefix  = local.trusted_operator_cidr
  security_group_id = openstack_networking_secgroup_v2.home_assistant_provider.id
}

resource "openstack_networking_port_v2" "hermes" {
  name               = "hermes-services"
  network_id         = data.openstack_networking_network_v2.services.id
  admin_state_up     = true
  security_group_ids = [openstack_networking_secgroup_v2.service_ssh.id]
  tags               = local.tags

  fixed_ip {
    subnet_id  = data.openstack_networking_subnet_v2.services.id
    ip_address = "192.168.80.11"
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "openstack_networking_port_v2" "home_assistant_services" {
  name           = "home-assistant-services"
  network_id     = data.openstack_networking_network_v2.services.id
  admin_state_up = true
  security_group_ids = [
    openstack_networking_secgroup_v2.home_assistant_private.id,
    openstack_networking_secgroup_v2.service_ssh.id,
  ]
  tags = local.tags

  fixed_ip {
    subnet_id  = data.openstack_networking_subnet_v2.services.id
    ip_address = "192.168.80.10"
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "openstack_networking_port_v2" "home_assistant_provider" {
  name               = "home-assistant-provider"
  network_id         = data.openstack_networking_network_v2.public.id
  admin_state_up     = true
  mac_address        = "fa:16:3e:80:00:10"
  security_group_ids = [openstack_networking_secgroup_v2.home_assistant_provider.id]
  tags               = local.tags

  fixed_ip {
    subnet_id  = data.openstack_networking_subnet_v2.public.id
    ip_address = "10.21.40.120"
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "openstack_blockstorage_volume_v3" "hermes_root" {
  name        = "hermes-root-${local.image_revision_short}"
  description = "Retained NixOS root for Hermes"
  size        = 80
  image_id    = data.openstack_images_image_v2.hermes.id

  metadata = {
    image_source_revision = var.image_revision
    managed_by            = "opentofu"
    service               = "hermes"
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "openstack_blockstorage_volume_v3" "home_assistant_root" {
  name        = "home-assistant-root-${local.image_revision_short}"
  description = "Retained NixOS root for Home Assistant"
  size        = 100
  image_id    = data.openstack_images_image_v2.home_assistant.id

  metadata = {
    image_source_revision = var.image_revision
    managed_by            = "opentofu"
    service               = "home-assistant"
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "openstack_compute_instance_v2" "hermes" {
  name                = "hermes"
  flavor_id           = data.openstack_compute_flavor_v2.services.id
  config_drive        = true
  stop_before_destroy = true

  block_device {
    uuid                  = openstack_blockstorage_volume_v3.hermes_root.id
    source_type           = "volume"
    destination_type      = "volume"
    boot_index            = 0
    delete_on_termination = false
  }

  network {
    port = openstack_networking_port_v2.hermes.id
  }

  metadata = {
    image_source_revision = var.image_revision
    managed_by            = "opentofu"
    service               = "hermes"
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "openstack_compute_instance_v2" "home_assistant" {
  name                = "home-assistant"
  flavor_id           = data.openstack_compute_flavor_v2.services.id
  config_drive        = true
  stop_before_destroy = true

  block_device {
    uuid                  = openstack_blockstorage_volume_v3.home_assistant_root.id
    source_type           = "volume"
    destination_type      = "volume"
    boot_index            = 0
    delete_on_termination = false
  }

  network {
    port = openstack_networking_port_v2.home_assistant_services.id
  }

  network {
    port = openstack_networking_port_v2.home_assistant_provider.id
  }

  metadata = {
    image_source_revision = var.image_revision
    managed_by            = "opentofu"
    service               = "home-assistant"
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "openstack_networking_floatingip_v2" "hermes" {
  pool        = data.openstack_networking_network_v2.public.name
  subnet_id   = data.openstack_networking_subnet_v2.public.id
  address     = "10.21.40.121"
  port_id     = openstack_networking_port_v2.hermes.id
  fixed_ip    = "192.168.80.11"
  description = "Hermes administration from the trusted operator LAN"
  tags        = local.tags

  lifecycle {
    prevent_destroy = true
  }
}

output "hermes_private_address" {
  description = "Hermes address on the services network"
  value       = "192.168.80.11"
}

output "hermes_provider_address" {
  description = "Hermes floating address reachable from the trusted operator LAN"
  value       = openstack_networking_floatingip_v2.hermes.address
}

output "home_assistant_private_address" {
  description = "Home Assistant address used by in-cluster ingress"
  value       = "192.168.80.10"
}

output "home_assistant_provider_address" {
  description = "Home Assistant direct address for local discovery"
  value       = "10.21.40.120"
}

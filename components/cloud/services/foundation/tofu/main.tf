terraform {
  required_version = ">= 1.12.1, < 1.13.0"

  required_providers {
    openstack = {
      source  = "terraform-provider-openstack/openstack"
      version = "= 3.4.0"
    }
  }
}

provider "openstack" {}

locals {
  region = "RegionOne"
  tags   = ["managed-by-opentofu", "platform-services"]
}

data "openstack_identity_user_v3" "admin" {
  name      = "admin"
  domain_id = "default"
}

data "openstack_identity_role_v3" "admin" {
  name = "admin"
}

data "openstack_networking_network_v2" "public" {
  name     = "public"
  external = true
}

resource "openstack_identity_project_v3" "services" {
  name        = "services"
  description = "Self-hosted application services"
  domain_id   = "default"
  enabled     = true
  tags        = local.tags
}

resource "openstack_identity_role_assignment_v3" "services_admin" {
  project_id = openstack_identity_project_v3.services.id
  user_id    = data.openstack_identity_user_v3.admin.id
  role_id    = data.openstack_identity_role_v3.admin.id
}

resource "openstack_compute_flavor_v2" "services_master" {
  name        = "services.master"
  description = "Magnum services control plane: 2 vCPU, 4 GiB RAM, 20 GiB root"
  ram         = 4096
  vcpus       = 2
  disk        = 20
  is_public   = false
}

resource "openstack_compute_flavor_v2" "services_master_v2" {
  name        = "services.master.v2"
  description = "Magnum services control plane v2: 2 vCPU, 8 GiB RAM, 20 GiB root"
  ram         = 8192
  vcpus       = 2
  disk        = 20
  is_public   = false
}

resource "openstack_compute_flavor_v2" "services_worker" {
  name        = "services.worker"
  description = "Magnum services worker: 4 vCPU, 12 GiB RAM, 40 GiB root"
  ram         = 12288
  vcpus       = 4
  disk        = 40
  is_public   = false
}

resource "openstack_compute_flavor_access_v2" "services_master" {
  flavor_id = openstack_compute_flavor_v2.services_master.id
  tenant_id = openstack_identity_project_v3.services.id
}

resource "openstack_compute_flavor_access_v2" "services_master_v2" {
  flavor_id = openstack_compute_flavor_v2.services_master_v2.id
  tenant_id = openstack_identity_project_v3.services.id
}

resource "openstack_compute_flavor_access_v2" "services_worker" {
  flavor_id = openstack_compute_flavor_v2.services_worker.id
  tenant_id = openstack_identity_project_v3.services.id
}

resource "openstack_networking_network_v2" "services" {
  name                  = "services"
  description           = "Private network for the self-hosted services cluster"
  tenant_id             = openstack_identity_project_v3.services.id
  admin_state_up        = true
  port_security_enabled = true
  mtu                   = 1442
  tags                  = local.tags
}

resource "openstack_networking_subnet_v2" "services" {
  name            = "services-v4"
  description     = "IPv4 subnet for the self-hosted services cluster"
  tenant_id       = openstack_identity_project_v3.services.id
  network_id      = openstack_networking_network_v2.services.id
  cidr            = "192.168.80.0/24"
  ip_version      = 4
  gateway_ip      = "192.168.80.1"
  enable_dhcp     = true
  dns_nameservers = ["10.21.40.1"]
  tags            = local.tags

  allocation_pool {
    start = "192.168.80.20"
    end   = "192.168.80.239"
  }
}

resource "openstack_networking_router_v2" "services" {
  name                = "services"
  description         = "SNAT and controlled provider-network ingress for services"
  tenant_id           = openstack_identity_project_v3.services.id
  admin_state_up      = true
  external_network_id = data.openstack_networking_network_v2.public.id
  enable_snat         = true
  tags                = local.tags
}

resource "openstack_networking_router_interface_v2" "services" {
  router_id = openstack_networking_router_v2.services.id
  subnet_id = openstack_networking_subnet_v2.services.id
}

resource "openstack_compute_quotaset_v2" "services" {
  project_id           = openstack_identity_project_v3.services.id
  cores                = 48
  instances            = 16
  key_pairs            = 20
  ram                  = 131072
  server_groups        = 16
  server_group_members = 32
}

resource "openstack_networking_quota_v2" "services" {
  project_id          = openstack_identity_project_v3.services.id
  floatingip          = 16
  network             = 8
  port                = 400
  rbac_policy         = 16
  router              = 8
  security_group      = 64
  security_group_rule = 400
  subnet              = 16
  subnetpool          = 4
}

resource "openstack_blockstorage_quotaset_v3" "services" {
  project_id           = openstack_identity_project_v3.services.id
  volumes              = 100
  snapshots            = 100
  gigabytes            = 3000
  per_volume_gigabytes = 1000
  backups              = 30
  backup_gigabytes     = 1000
  groups               = 20
}

resource "openstack_lb_quota_v2" "services" {
  project_id     = openstack_identity_project_v3.services.id
  loadbalancer   = 16
  listener       = 64
  member         = 256
  pool           = 64
  health_monitor = 64
}

output "project_id" {
  description = "Keystone project that owns the services platform"
  value       = openstack_identity_project_v3.services.id
}

output "network_id" {
  description = "Neutron network selected by the Magnum template"
  value       = openstack_networking_network_v2.services.id
}

output "subnet_id" {
  description = "Neutron subnet selected by the Magnum template"
  value       = openstack_networking_subnet_v2.services.id
}

# CI gets its own project, network, quota and application-specific egress rules.
# Guest job code never receives cloud credentials or access to the services LAN.
resource "openstack_identity_project_v3" "ci" {
  name        = "forge-ci"
  description = "Isolated Forgejo Actions build and game-test runners"
  domain_id   = "default"
  tags        = ["managed-by-opentofu", "forge-ci"]
}

resource "openstack_identity_role_assignment_v3" "ci_admin" {
  project_id = openstack_identity_project_v3.ci.id
  user_id    = data.openstack_identity_user_v3.admin.id
  role_id    = data.openstack_identity_role_v3.admin.id
}

# Native job controllers receive a project-member application credential.
# Never give the controller the administrator role used for provisioning.
data "openstack_identity_role_v3" "forge_runner_member" {
  name = "member"
}
resource "openstack_identity_role_assignment_v3" "ci_member" {
  project_id = openstack_identity_project_v3.ci.id
  user_id    = data.openstack_identity_user_v3.admin.id
  role_id    = data.openstack_identity_role_v3.forge_runner_member.id
}

locals {
  gitlab_flavors = {
    gitlab        = { ram = 4096, vcpus = 4, ci = false }
    gitlab-master = { ram = 4096, vcpus = 2, ci = false }
    gitlab-worker = { ram = 12288, vcpus = 6, ci = false }
    forge-windows = { ram = 12288, vcpus = 6, ci = true }
    forge-macos   = { ram = 12288, vcpus = 6, ci = true }
  }
}

resource "openstack_compute_flavor_v2" "gitlab" {
  for_each  = local.gitlab_flavors
  name      = each.key
  ram       = each.value.ram
  vcpus     = each.value.vcpus
  disk      = 0
  is_public = false
  # Windows 11 Pro supports two sockets. Expose native runner CPUs as cores
  # in one socket; Quickemu also needs a stable nested guest topology.
  extra_specs = each.value.ci ? {
    "hw:cpu_sockets" = "1"
    "hw:cpu_cores"   = "6"
    "hw:cpu_threads" = "1"
  } : {}
}

resource "openstack_compute_flavor_access_v2" "gitlab" {
  for_each  = local.gitlab_flavors
  flavor_id = openstack_compute_flavor_v2.gitlab[each.key].id
  tenant_id = each.value.ci ? openstack_identity_project_v3.ci.id : openstack_identity_project_v3.gitlab.id
}

resource "openstack_networking_network_v2" "ci" {
  name                  = "forge-ci"
  tenant_id             = openstack_identity_project_v3.ci.id
  port_security_enabled = true
  mtu                   = 1442
}

resource "openstack_networking_subnet_v2" "ci" {
  name            = "forge-ci-v4"
  tenant_id       = openstack_identity_project_v3.ci.id
  network_id      = openstack_networking_network_v2.ci.id
  cidr            = "192.168.81.0/24"
  gateway_ip      = "192.168.81.1"
  ip_version      = 4
  enable_dhcp     = true
  dns_nameservers = ["10.21.40.1"]
  allocation_pool {
    start = "192.168.81.20"
    end   = "192.168.81.99"
  }
}

resource "openstack_networking_router_v2" "ci" {
  name                = "forge-ci"
  tenant_id           = openstack_identity_project_v3.ci.id
  external_network_id = data.openstack_networking_network_v2.public.id
  enable_snat         = true
}

resource "openstack_networking_router_interface_v2" "ci" {
  router_id = openstack_networking_router_v2.ci.id
  subnet_id = openstack_networking_subnet_v2.ci.id
}

resource "openstack_compute_quotaset_v2" "ci" {
  project_id = openstack_identity_project_v3.ci.id
  cores      = 24
  ram        = 49152
  instances  = 6
  key_pairs  = 10
}

resource "openstack_networking_quota_v2" "ci" {
  project_id          = openstack_identity_project_v3.ci.id
  floatingip          = 4
  network             = 2
  subnet              = 2
  router              = 1
  port                = 20
  security_group      = 8
  security_group_rule = 300
}

resource "openstack_blockstorage_quotaset_v3" "ci" {
  project_id           = openstack_identity_project_v3.ci.id
  volumes              = 12
  snapshots            = 12
  gigabytes            = 1500
  per_volume_gigabytes = 500
}

# This project owns a separate Magnum/CAPI cluster, not a services-v1 nodegroup.
resource "openstack_identity_project_v3" "gitlab" {
  name        = "gitlab"
  description = "Private GitLab Kubernetes cluster and stateful backend"
  domain_id   = "default"
  tags        = ["managed-by-opentofu", "gitlab"]
}
resource "openstack_identity_role_assignment_v3" "gitlab_admin" {
  project_id = openstack_identity_project_v3.gitlab.id
  user_id    = data.openstack_identity_user_v3.admin.id
  role_id    = data.openstack_identity_role_v3.admin.id
}
resource "openstack_networking_network_v2" "gitlab" {
  name                  = "gitlab"
  tenant_id             = openstack_identity_project_v3.gitlab.id
  port_security_enabled = true
  mtu                   = 1442
}
resource "openstack_networking_subnet_v2" "gitlab" {
  name            = "gitlab-v4"
  tenant_id       = openstack_identity_project_v3.gitlab.id
  network_id      = openstack_networking_network_v2.gitlab.id
  cidr            = "192.168.82.0/24"
  gateway_ip      = "192.168.82.1"
  ip_version      = 4
  enable_dhcp     = true
  dns_nameservers = ["10.21.40.1"]
  allocation_pool {
    start = "192.168.82.20"
    end   = "192.168.82.239"
  }
}
resource "openstack_networking_router_v2" "gitlab" {
  name                = "gitlab"
  tenant_id           = openstack_identity_project_v3.gitlab.id
  external_network_id = data.openstack_networking_network_v2.public.id
  enable_snat         = true
  external_fixed_ip {
    subnet_id  = data.openstack_networking_subnet_v2.public.id
    ip_address = "10.21.40.129"
  }
}
resource "openstack_networking_router_interface_v2" "gitlab" {
  router_id = openstack_networking_router_v2.gitlab.id
  subnet_id = openstack_networking_subnet_v2.gitlab.id
}
resource "openstack_compute_quotaset_v2" "gitlab" {
  project_id = openstack_identity_project_v3.gitlab.id
  cores      = 24
  ram        = 32768
  instances  = 6
  key_pairs  = 10
}
resource "openstack_networking_quota_v2" "gitlab" {
  project_id          = openstack_identity_project_v3.gitlab.id
  floatingip          = 8
  network             = 2
  subnet              = 2
  router              = 1
  port                = 40
  security_group      = 12
  security_group_rule = 150
}
resource "openstack_blockstorage_quotaset_v3" "gitlab" {
  project_id           = openstack_identity_project_v3.gitlab.id
  volumes              = 20
  snapshots            = 20
  gigabytes            = 2000
  per_volume_gigabytes = 1000
}

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
data "openstack_networking_network_v2" "public" { name = "public" }
data "openstack_networking_subnet_v2" "public" { name = "public-v4" }
data "openstack_identity_user_v3" "admin" { name = "admin" }
data "openstack_identity_role_v3" "admin" { name = "admin" }

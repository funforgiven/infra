terraform {
  required_version = ">= 1.12.1, < 1.13.0"
  required_providers {
    netbird = {
      source  = "netbirdio/netbird"
      version = "= 0.0.10"
    }
  }
}

variable "netbird_token" {
  type      = string
  sensitive = true
}

variable "default_policy_id" {
  type = string
}

variable "netbird_client_id" {
  type      = string
  sensitive = true
}

variable "netbird_client_secret" {
  type      = string
  sensitive = true
}

provider "netbird" {
  management_url = "https://netbird-api.fahrican.com"
  token          = var.netbird_token
}

data "netbird_group" "all" {
  name = "All"
}

# Enrollment disables this before any client/connector can join. Importing it
# gives GitOps continuing ownership: a dashboard edit cannot enable full mesh.
import {
  to = netbird_policy.default
  id = var.default_policy_id
}

resource "netbird_policy" "default" {
  name        = "Default"
  description = "Disabled: service access is explicitly one-way"
  enabled     = false
  rule {
    name          = "Default"
    action        = "accept"
    enabled       = false
    bidirectional = true
    protocol      = "all"
    sources       = [data.netbird_group.all.id]
    destinations  = [data.netbird_group.all.id]
  }
}

resource "netbird_account_settings" "homelab" {
  network_range                      = "100.104.0.0/16"
  dns_domain                         = "peers.vpn.fahrican.com"
  peer_login_expiration_enabled      = true
  peer_login_expiration              = 2592000
  peer_inactivity_expiration_enabled = true
  peer_inactivity_expiration         = 604800
  regular_users_view_blocked         = true
  groups_propagation_enabled         = true
  peer_expose_enabled                = false
  auto_update_version                = "disabled"
}

resource "netbird_identity_provider" "zitadel" {
  name          = "Fahrican"
  type          = "zitadel"
  issuer        = "https://auth.cloud.fahrican.com"
  client_id     = var.netbird_client_id
  client_secret = var.netbird_client_secret
  depends_on    = [netbird_policy.default, netbird_account_settings.homelab]
}

resource "netbird_group" "services" {
  name = "private-services"
  # Kubernetes owns resource membership. ToFu owns this group's identity only.
  lifecycle {
    ignore_changes = [resources]
  }
}

resource "netbird_policy" "services" {
  name        = "Private HTTPS services"
  description = "Enrolled service users may initiate HTTPS to the private gateway"
  enabled     = true
  rule {
    name          = "HTTPS"
    action        = "accept"
    enabled       = true
    bidirectional = false
    protocol      = "tcp"
    ports         = ["443"]
    sources       = [data.netbird_group.all.id]
    destinations  = [netbird_group.services.id]
  }
  depends_on = [netbird_policy.default]
}

resource "netbird_dns_zone" "operator" {
  name                 = "Kubernetes service resources"
  domain               = "vpn.fahrican.com"
  enabled              = true
  enable_search_domain = false
  distribution_groups  = [data.netbird_group.all.id]
}

locals {
  service_hosts = toset([
    "audiomuse", "cache", "git", "home", "mail-admin", "music", "unifi", "upload", "wallos",
  ])
}

# Individual zones deliberately leave public mail/JMAP, ZITADEL, and the rest
# of fahrican.com DNS untouched. With NetBird disconnected, LAN DNS still
# resolves these names to the existing LAN gateway.
resource "netbird_dns_zone" "service" {
  for_each             = local.service_hosts
  name                 = "Private service ${each.key}"
  domain               = "${each.key}.fahrican.com"
  enabled              = true
  enable_search_domain = false
  distribution_groups  = [data.netbird_group.all.id]
}

resource "netbird_dns_record" "service" {
  for_each = local.service_hosts
  zone_id  = netbird_dns_zone.service[each.key].id
  name     = "${each.key}.fahrican.com"
  type     = "A"
  content  = "172.24.0.80"
  ttl      = 60
}

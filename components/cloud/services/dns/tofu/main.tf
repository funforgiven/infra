terraform {
  required_version = ">= 1.12.1, < 1.13.0"

  required_providers {
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = "= 5.23.0"
    }
  }
}

provider "cloudflare" {}

variable "mail_ipv4_address" {
  description = "Stable public IPv4 address of the Hetzner mail edge"
  type        = string

  validation {
    condition = can(cidrhost("${var.mail_ipv4_address}/32", 0)) && !contains([
      "0.0.0.0",
      "192.0.2.255",
    ], var.mail_ipv4_address)
    error_message = "mail_ipv4_address must be the activated mail edge address, not a sentinel."
  }
}

variable "resend_records_json" {
  description = "Provider-issued public DNS verification records from the Resend domain reconciler"
  type        = string

  validation {
    condition     = try(length(jsondecode(var.resend_records_json)) > 0, false)
    error_message = "resend_records_json must be a non-empty JSON array from the Resend API reconciler."
  }
}

data "cloudflare_zone" "fahrican" {
  filter = {
    name   = "fahrican.com"
    status = "active"
  }
}

locals {
  services_gateway_address = "10.21.40.122"
  private_services = toset([
    "home",
    "inbox",
    "music",
  ])
  mail_hosts = toset([
    "autoconfig",
    "autodiscover",
    "mail",
  ])
  resend_records = {
    for index, record in jsondecode(var.resend_records_json) :
    "${lower(record.type)}-${index}" => record
    if contains(["CNAME", "MX", "TXT"], record.type)
  }
}

resource "cloudflare_dns_record" "private_services" {
  for_each = local.private_services

  zone_id = data.cloudflare_zone.fahrican.zone_id
  name    = "${each.key}.fahrican.com"
  type    = "A"
  content = local.services_gateway_address
  ttl     = 300
  proxied = false
  comment = "Git-managed routed-LAN endpoint; intentionally not Internet-routable"
}

resource "cloudflare_dns_record" "mail_hosts" {
  for_each = local.mail_hosts

  zone_id = data.cloudflare_zone.fahrican.zone_id
  name    = "${each.key}.fahrican.com"
  type    = "A"
  content = var.mail_ipv4_address
  ttl     = 300
  proxied = false
  comment = "Git-managed Stalwart mail edge"
}

resource "cloudflare_dns_record" "mail_exchange" {
  zone_id  = data.cloudflare_zone.fahrican.zone_id
  name     = "fahrican.com"
  type     = "MX"
  content  = "mail.fahrican.com"
  priority = 10
  ttl      = 300
  comment  = "Git-managed inbound mail route"
}

resource "cloudflare_dns_record" "dmarc" {
  zone_id = data.cloudflare_zone.fahrican.zone_id
  name    = "_dmarc.fahrican.com"
  type    = "TXT"
  content = "v=DMARC1; p=quarantine; rua=mailto:dmarc@fahrican.com; adkim=s; aspf=s; pct=100"
  ttl     = 300
  comment = "Git-managed DMARC policy"
}

resource "cloudflare_dns_record" "resend_verification" {
  for_each = local.resend_records

  zone_id = data.cloudflare_zone.fahrican.zone_id
  name = endswith(each.value.name, ".fahrican.com") ? (
    each.value.name
  ) : "${each.value.name}.fahrican.com"
  type = each.value.type
  content = each.value.type == "TXT" ? (
    trim(each.value.value, "\"")
  ) : trimsuffix(each.value.value, ".")
  priority = each.value.type == "MX" ? try(each.value.priority, 10) : null
  ttl      = 300
  proxied  = false
  comment  = "Git-managed Resend ${each.value.record} verification"
}

output "services_gateway_address" {
  description = "Routed-LAN address published for private application endpoints"
  value       = local.services_gateway_address
}

output "mail_ipv4_address" {
  description = "Public mail address published by this root"
  value       = var.mail_ipv4_address
}

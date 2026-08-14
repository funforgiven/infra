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

variable "zone_id" {
  description = "Cloudflare zone identifier for fahrican.com"
  type        = string
  sensitive   = true

  validation {
    condition     = can(regex("^[0-9a-f]{32}$", var.zone_id))
    error_message = "zone_id must be the exact 32-character Cloudflare zone identifier."
  }
}

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

locals {
  services_gateway_address = "10.21.40.122"
  private_services = toset([
    "home",
    "inbox",
    "keep",
    "music",
    "search",
  ])
  mail_hosts = toset([
    "autoconfig",
    "autodiscover",
    "mail",
  ])
}

resource "cloudflare_dns_record" "private_services" {
  for_each = local.private_services

  zone_id = var.zone_id
  name    = "${each.key}.fahrican.com"
  type    = "A"
  content = local.services_gateway_address
  ttl     = 300
  proxied = false
  comment = "Git-managed routed-LAN endpoint; intentionally not Internet-routable"
}

resource "cloudflare_dns_record" "mail_hosts" {
  for_each = local.mail_hosts

  zone_id = var.zone_id
  name    = "${each.key}.fahrican.com"
  type    = "A"
  content = var.mail_ipv4_address
  ttl     = 300
  proxied = false
  comment = "Git-managed Stalwart mail edge"
}

resource "cloudflare_dns_record" "mail_exchange" {
  zone_id  = var.zone_id
  name     = "fahrican.com"
  type     = "MX"
  content  = "mail.fahrican.com"
  priority = 10
  ttl      = 300
  comment  = "Git-managed inbound mail route"
}

resource "cloudflare_dns_record" "dmarc" {
  zone_id = var.zone_id
  name    = "_dmarc.fahrican.com"
  type    = "TXT"
  content = "v=DMARC1; p=quarantine; rua=mailto:dmarc@fahrican.com; adkim=s; aspf=s; pct=100"
  ttl     = 300
  comment = "Git-managed DMARC policy"
}

output "services_gateway_address" {
  description = "Routed-LAN address published for private application endpoints"
  value       = local.services_gateway_address
}

output "mail_ipv4_address" {
  description = "Public mail address published by this root"
  value       = var.mail_ipv4_address
}

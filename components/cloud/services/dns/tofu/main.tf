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
  description = "Stable public IPv4 address of the active mail origin"
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
    "audiomuse",
    "home",
    "gitlab",
    "kas",
    "registry",
    "music",
    "upload",
    "wallos",
  ])
  mail_hosts = toset([
    "autoconfig",
    "autodiscover",
    "mail",
    "mta-sts",
    "ua-auto-config",
  ])
  resend_records = {
    for index, record in jsondecode(var.resend_records_json) :
    "${lower(record.type)}-${index}" => record
    if contains(["CNAME", "MX", "TXT"], record.type)
  }
  stalwart_dkim_records = {
    "v1-ed25519-20260823" = "v=DKIM1; k=ed25519; h=sha256; p=gSs541DU7F8OPrKAXEIMScEpz22TQw2TXysIjurJXPI="
    "v1-rsa-20260823"     = "v=DKIM1; k=rsa; h=sha256; p=MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAqvXkBsulmdXskGapqEpB8uMBjd1j6FvDRp8PeQf9rDXY5L1PeEi/2nA0T7EVRTSgydEzFgnCkhNARx6qEO2lozFNXU6omb6Up8aWQXCZod/kccx0K968mK5KNsyMFef8DoxsoeQkVwzRD4gsr4Sc9K0T0WkIM/pIEsot/mnism4WyhuCSpDO0bZWGc918Irrogx/8XIbV0pEMOp2ze29Wk5WI2a/J9ZasPWewbnFzLdRrxocZm8v3f3UV9SFElkXPaJygQCds4mvsizcDYT9quOcORqrnazimQc4ODZ34S1m5J5VYsJq2TbilPko7qCXHu3zSliJuhgKFuQkWEhSbQIDAQAB"
  }
}

resource "cloudflare_dns_record" "private_services" {
  for_each = local.private_services

  zone_id = data.cloudflare_zone.fahrican.zone_id
  name    = "${each.key}.fahrican.com"
  type    = "A"
  content = contains(["gitlab", "registry", "kas"], each.key) ? "10.21.40.127" : local.services_gateway_address
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

resource "cloudflare_dns_record" "stalwart_dkim" {
  for_each = local.stalwart_dkim_records

  zone_id = data.cloudflare_zone.fahrican.zone_id
  name    = "${each.key}._domainkey.fahrican.com"
  type    = "TXT"
  content = each.value
  ttl     = 300
  comment = "Git-managed Stalwart DKIM public key"
}

resource "cloudflare_dns_record" "mail_spf" {
  zone_id = data.cloudflare_zone.fahrican.zone_id
  name    = "mail.fahrican.com"
  type    = "TXT"
  content = "v=spf1 a -all"
  ttl     = 300
  comment = "Git-managed Stalwart host SPF policy"
}

resource "cloudflare_dns_record" "apex_spf" {
  zone_id = data.cloudflare_zone.fahrican.zone_id
  name    = "fahrican.com"
  type    = "TXT"
  content = "v=spf1 mx -all"
  ttl     = 300
  comment = "Git-managed Stalwart domain SPF policy"
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

resource "cloudflare_dns_record" "gitlab_s3" {
  zone_id = data.cloudflare_zone.fahrican.zone_id
  name    = "gitlab-s3.cloud.fahrican.com"
  type    = "A"
  content = "10.21.20.130"
  proxied = false
  ttl     = 300
}

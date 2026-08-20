terraform {
  required_version = ">= 1.12.1, < 1.13.0"

  required_providers {
    hcloud = {
      source  = "hetznercloud/hcloud"
      version = "= 1.68.0"
    }
  }
}

provider "hcloud" {}

variable "management_cidrs_json" {
  description = "JSON-encoded public CIDRs permitted to bootstrap and administer the mail edge over SSH"
  type        = string

  validation {
    condition = length(try(tolist(jsondecode(var.management_cidrs_json)), [])) > 0 && alltrue([
      for cidr in try(tolist(jsondecode(var.management_cidrs_json)), []) :
      can(cidrhost(cidr, 0)) && cidr != "203.0.113.255/32"
    ])
    error_message = "Every management entry must be an explicit valid CIDR, not a documentation sentinel."
  }
}

locals {
  management_cidrs = try(tolist(jsondecode(var.management_cidrs_json)), [])
  labels = {
    environment = "production"
    managed_by  = "opentofu"
    service     = "mail-edge"
  }
}

resource "hcloud_ssh_key" "operator" {
  name       = "funforgiven-mail-edge-bootstrap"
  public_key = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIL1nHHxNA1YUl+89HhieA+YOyOLYJaSRBmutEOVxVQeB github-funforgiven-2026-07-18"
  labels     = local.labels
}

resource "hcloud_primary_ip" "mail_edge" {
  name        = "mail-edge-ipv4"
  type        = "ipv4"
  location    = "hel1"
  auto_delete = false
  labels      = local.labels

  lifecycle {
    prevent_destroy = true
  }
}

resource "hcloud_firewall" "mail_edge" {
  name   = "mail-edge"
  labels = local.labels

  rule {
    direction   = "in"
    protocol    = "tcp"
    port        = "22"
    source_ips  = local.management_cidrs
    description = "SSH administration from explicit operator networks"
  }

  rule {
    direction = "in"
    protocol  = "tcp"
    port      = "25"
    source_ips = [
      "0.0.0.0/0",
      "::/0",
    ]
    description = "SMTP delivery"
  }

  rule {
    direction = "in"
    protocol  = "tcp"
    port      = "80"
    source_ips = [
      "0.0.0.0/0",
      "::/0",
    ]
    description = "ACME HTTP-01"
  }

  rule {
    direction = "in"
    protocol  = "tcp"
    port      = "443"
    source_ips = [
      "0.0.0.0/0",
      "::/0",
    ]
    description = "Stalwart HTTPS"
  }

  rule {
    direction = "in"
    protocol  = "tcp"
    port      = "465"
    source_ips = [
      "0.0.0.0/0",
      "::/0",
    ]
    description = "Implicit TLS message submission"
  }

  rule {
    direction = "in"
    protocol  = "tcp"
    port      = "587"
    source_ips = [
      "0.0.0.0/0",
      "::/0",
    ]
    description = "STARTTLS message submission"
  }

  rule {
    direction = "in"
    protocol  = "tcp"
    port      = "993"
    source_ips = [
      "0.0.0.0/0",
      "::/0",
    ]
    description = "IMAP over TLS"
  }

  rule {
    direction = "in"
    protocol  = "icmp"
    source_ips = [
      "0.0.0.0/0",
      "::/0",
    ]
    description = "Path MTU and reachability diagnostics"
  }
}

resource "hcloud_server" "mail_edge" {
  name        = "mail-edge"
  image       = "debian-13"
  server_type = "cx23"
  location    = "hel1"
  ssh_keys    = [hcloud_ssh_key.operator.id]
  firewall_ids = [
    hcloud_firewall.mail_edge.id,
  ]
  labels                   = local.labels
  backups                  = true
  delete_protection        = true
  rebuild_protection       = true
  shutdown_before_deletion = true

  public_net {
    ipv4_enabled = true
    ipv4         = hcloud_primary_ip.mail_edge.id
    ipv6_enabled = false
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "hcloud_rdns" "mail_edge" {
  primary_ip_id = hcloud_primary_ip.mail_edge.id
  ip_address    = hcloud_primary_ip.mail_edge.ip_address
  dns_ptr       = "mail.fahrican.com"
}

output "ipv4_address" {
  description = "Stable mail edge address used for DNS and NixOS installation"
  value       = hcloud_primary_ip.mail_edge.ip_address
}

output "server_id" {
  description = "Hetzner Cloud server identifier"
  value       = hcloud_server.mail_edge.id
}

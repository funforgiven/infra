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

locals {
  host_backup_buckets = toset([
    "fahrican-hermes-backup",
    "fahrican-home-assistant-backup",
    "fahrican-mail-edge-backup",
  ])
}

data "cloudflare_zone" "fahrican" {
  filter = {
    name   = "fahrican.com"
    status = "active"
  }
}

resource "cloudflare_r2_bucket" "services_backup" {
  account_id    = data.cloudflare_zone.fahrican.account.id
  name          = "fahrican-services-backup"
  location      = "WEUR"
  storage_class = "Standard"

  lifecycle {
    prevent_destroy = true
  }
}

resource "cloudflare_r2_bucket" "host_backup" {
  for_each = local.host_backup_buckets

  account_id    = data.cloudflare_zone.fahrican.account.id
  name          = each.value
  location      = "WEUR"
  storage_class = "Standard"

  lifecycle {
    prevent_destroy = true
  }
}

output "bucket_name" {
  description = "R2 bucket used by the services cluster backup controller"
  value       = cloudflare_r2_bucket.services_backup.name
}

output "endpoint" {
  description = "S3-compatible endpoint for the account that owns the R2 bucket"
  value       = "https://${data.cloudflare_zone.fahrican.account.id}.r2.cloudflarestorage.com"
}

output "host_bucket_names" {
  description = "Retained per-host buckets used by encrypted Restic repositories"
  value       = sort([for bucket in cloudflare_r2_bucket.host_backup : bucket.name])
}

output "region" {
  description = "S3 compatibility region used by R2 clients"
  value       = "auto"
}

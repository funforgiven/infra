# The recovery bucket's settings. Application keys are minted by hand (see
# secrets/README.md) so a rotation never revokes a key still in use.
terraform {
  required_version = ">= 1.12.1, < 2.0.0"

  required_providers {
    b2 = {
      source  = "Backblaze/b2"
      version = "= 0.14.0"
    }
  }
}

# Reads B2_APPLICATION_KEY_ID and B2_APPLICATION_KEY (an account-level key).
provider "b2" {}

locals {
  # Hidden versions are kept 30 days under every prefix that holds backups,
  # including retained archives of the retired deployment.
  retained_prefixes = [
    "management/etcd/",
    "services/etcd/",
    "services/hosts/gitlab/",
    "services/hosts/hermes/",
    "services/hosts/home-assistant/",
    "services/hosts/mail-aws/",
    "services/hosts/mail-edge/",
    "services/hosts/unifi/",
    "services/kubernetes/",
    "undercloud/etcd/",
    "undercloud/openstack/",
    "undercloud/zitadel/",
  ]
}

resource "b2_bucket" "recovery" {
  bucket_name = "fahrican-cloud-recovery"
  bucket_type = "allPrivate"

  default_server_side_encryption {
    mode      = "SSE-B2"
    algorithm = "AES256"
  }

  dynamic "lifecycle_rules" {
    for_each = local.retained_prefixes
    content {
      file_name_prefix             = lifecycle_rules.value
      days_from_hiding_to_deleting = 30
    }
  }

  lifecycle {
    prevent_destroy = true
  }
}

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
  description = "Retained controller interface during the final destroy apply"
  type        = string
}

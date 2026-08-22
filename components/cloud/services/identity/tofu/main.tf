terraform {
  required_version = ">= 1.12.1, < 1.13.0"

  required_providers {
    zitadel = {
      source  = "zitadel/zitadel"
      version = "= 3.3.0"
    }
  }
}

variable "jwt_profile_json" {
  type      = string
  sensitive = true
}

provider "zitadel" {
  domain           = "auth.cloud.fahrican.com"
  port             = "443"
  jwt_profile_json = var.jwt_profile_json
}

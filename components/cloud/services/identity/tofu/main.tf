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

locals {
  org_id = "385431068645343545"
}

provider "zitadel" {
  domain           = "auth.cloud.fahrican.com"
  port             = "443"
  jwt_profile_json = var.jwt_profile_json
}

data "zitadel_projects" "infrastructure" {
  org_id      = local.org_id
  name        = "Infrastructure"
  name_method = "TEXT_QUERY_METHOD_EQUALS"
}

resource "zitadel_application_oidc" "karakeep" {
  org_id                       = local.org_id
  project_id                   = one(data.zitadel_projects.infrastructure.project_ids)
  name                         = "Karakeep"
  redirect_uris                = ["https://keep.fahrican.com/api/auth/callback/custom"]
  post_logout_redirect_uris    = ["https://keep.fahrican.com/"]
  response_types               = ["OIDC_RESPONSE_TYPE_CODE"]
  grant_types                  = ["OIDC_GRANT_TYPE_AUTHORIZATION_CODE", "OIDC_GRANT_TYPE_REFRESH_TOKEN"]
  app_type                     = "OIDC_APP_TYPE_WEB"
  auth_method_type             = "OIDC_AUTH_METHOD_TYPE_BASIC"
  version                      = "OIDC_VERSION_1_0"
  access_token_type            = "OIDC_TOKEN_TYPE_BEARER"
  access_token_role_assertion  = false
  id_token_role_assertion      = false
  id_token_userinfo_assertion  = true
  dev_mode                     = false
  additional_origins           = []
  skip_native_app_success_page = false
}

output "OAUTH_CLIENT_ID" {
  value     = zitadel_application_oidc.karakeep.client_id
  sensitive = true
}

output "OAUTH_CLIENT_SECRET" {
  value     = zitadel_application_oidc.karakeep.client_secret
  sensitive = true
}

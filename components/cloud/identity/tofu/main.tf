terraform {
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
  org_id             = "385431068645343545"
  breakglass_user_id = "385431068646064441"
}

provider "zitadel" {
  domain           = "auth.cloud.fahrican.com"
  port             = "443"
  jwt_profile_json = var.jwt_profile_json
}

resource "zitadel_project" "infrastructure" {
  org_id                   = local.org_id
  name                     = "Infrastructure"
  project_role_assertion   = true
  project_role_check       = true
  has_project_check        = true
  private_labeling_setting = "PRIVATE_LABELING_SETTING_ENFORCE_PROJECT_RESOURCE_OWNER_POLICY"
}

resource "zitadel_project_role" "infra_admin" {
  org_id       = local.org_id
  project_id   = zitadel_project.infrastructure.id
  role_key     = "infra-admin"
  display_name = "Infrastructure administrator"
  group        = "infrastructure"
}

resource "zitadel_project_role" "infra_viewer" {
  org_id       = local.org_id
  project_id   = zitadel_project.infrastructure.id
  role_key     = "infra-viewer"
  display_name = "Infrastructure viewer"
  group        = "infrastructure"
}

resource "zitadel_user_grant" "breakglass_admin" {
  org_id     = local.org_id
  project_id = zitadel_project.infrastructure.id
  user_id    = local.breakglass_user_id
  role_keys  = [zitadel_project_role.infra_admin.role_key]
}

resource "zitadel_login_policy" "fahrican" {
  org_id                        = local.org_id
  user_login                    = true
  allow_register                = false
  allow_external_idp            = false
  force_mfa                     = false
  force_mfa_local_only          = false
  passwordless_type             = "PASSWORDLESS_TYPE_ALLOWED"
  hide_password_reset           = false
  password_check_lifetime       = "240h0m0s"
  external_login_check_lifetime = "240h0m0s"
  multi_factor_check_lifetime   = "24h0m0s"
  mfa_init_skip_lifetime        = "720h0m0s"
  second_factor_check_lifetime  = "24h0m0s"
  ignore_unknown_usernames      = true
  default_redirect_uri          = "https://auth.cloud.fahrican.com/ui/console"
  second_factors                = ["SECOND_FACTOR_TYPE_OTP", "SECOND_FACTOR_TYPE_U2F"]
  multi_factors                 = ["MULTI_FACTOR_TYPE_U2F_WITH_VERIFICATION"]
  allow_domain_discovery        = false
  disable_login_with_email      = false
  disable_login_with_phone      = true
}

resource "zitadel_machine_user" "identity_controller" {
  org_id      = local.org_id
  user_name   = "tofu-identity-controller"
  name        = "OpenTofu identity controller"
  description = "Reconciles identity configuration from Git"
}

resource "zitadel_org_member" "identity_controller" {
  org_id  = local.org_id
  user_id = zitadel_machine_user.identity_controller.id
  roles   = ["ORG_OWNER"]
}

resource "zitadel_project_member" "identity_controller" {
  org_id     = local.org_id
  project_id = zitadel_project.infrastructure.id
  user_id    = zitadel_machine_user.identity_controller.id
  roles      = ["PROJECT_OWNER"]

  depends_on = [zitadel_org_member.identity_controller]
}

resource "zitadel_machine_key" "identity_controller" {
  org_id          = local.org_id
  user_id         = zitadel_machine_user.identity_controller.id
  key_type        = "KEY_TYPE_JSON"
  expiration_date = "2031-08-09T00:00:00Z"

  depends_on = [zitadel_org_member.identity_controller]
}

locals {
  web_oidc_apps = {
    forgejo = {
      name         = "Forgejo"
      redirect_uri = "https://git.fahrican.com/user/oauth2/ZITADEL/callback"
      post_logout  = "https://git.fahrican.com/"
    }
    grafana = {
      name         = "Grafana"
      redirect_uri = "https://grafana.cloud.fahrican.com/login/generic_oauth"
      post_logout  = "https://grafana.cloud.fahrican.com/"
    }
    openstack = {
      name         = "OpenStack"
      redirect_uri = "https://identity.cloud.fahrican.com/v3/redirect_uri"
      post_logout  = "https://dashboard.cloud.fahrican.com/"
    }
    sftpgo = {
      name         = "SFTPGo Music Upload"
      redirect_uri = "https://upload.fahrican.com/web/oidc/redirect"
      post_logout  = "https://upload.fahrican.com/web/client/logout"
    }
    navidrome = {
      name         = "Navidrome"
      redirect_uri = "https://music.fahrican.com/oauth2/callback"
      post_logout  = "https://music.fahrican.com/"
    }
    audiomuse = {
      name         = "AudioMuse"
      redirect_uri = "https://audiomuse.fahrican.com/oauth2/callback"
      post_logout  = "https://audiomuse.fahrican.com/"
    }
  }
}

resource "zitadel_application_oidc" "web" {
  for_each = local.web_oidc_apps

  org_id                       = local.org_id
  project_id                   = zitadel_project.infrastructure.id
  name                         = each.value.name
  redirect_uris                = [each.value.redirect_uri]
  post_logout_redirect_uris    = [each.value.post_logout]
  response_types               = ["OIDC_RESPONSE_TYPE_CODE"]
  grant_types                  = ["OIDC_GRANT_TYPE_AUTHORIZATION_CODE", "OIDC_GRANT_TYPE_REFRESH_TOKEN"]
  app_type                     = "OIDC_APP_TYPE_WEB"
  auth_method_type             = "OIDC_AUTH_METHOD_TYPE_BASIC"
  version                      = "OIDC_VERSION_1_0"
  access_token_type            = "OIDC_TOKEN_TYPE_BEARER"
  access_token_role_assertion  = true
  id_token_role_assertion      = true
  id_token_userinfo_assertion  = true
  dev_mode                     = false
  additional_origins           = []
  skip_native_app_success_page = false
}

# Keep Wallos separate from the shared BASIC-auth clients: it requires
# client_secret_post and may need credentials rotated independently.
moved {
  from = zitadel_application_oidc.web["wallos"]
  to   = zitadel_application_oidc.wallos
}

resource "terraform_data" "wallos_oidc_credential_generation" {
  input = 1
}

resource "zitadel_application_oidc" "wallos" {
  org_id                       = local.org_id
  project_id                   = zitadel_project.infrastructure.id
  name                         = "Wallos"
  redirect_uris                = ["https://wallos.fahrican.com/index.php"]
  post_logout_redirect_uris    = ["https://wallos.fahrican.com/"]
  response_types               = ["OIDC_RESPONSE_TYPE_CODE"]
  grant_types                  = ["OIDC_GRANT_TYPE_AUTHORIZATION_CODE", "OIDC_GRANT_TYPE_REFRESH_TOKEN"]
  app_type                     = "OIDC_APP_TYPE_WEB"
  auth_method_type             = "OIDC_AUTH_METHOD_TYPE_POST"
  version                      = "OIDC_VERSION_1_0"
  access_token_type            = "OIDC_TOKEN_TYPE_BEARER"
  access_token_role_assertion  = true
  id_token_role_assertion      = true
  id_token_userinfo_assertion  = true
  dev_mode                     = false
  additional_origins           = []
  skip_native_app_success_page = false

  lifecycle {
    replace_triggered_by = [terraform_data.wallos_oidc_credential_generation]
  }

  depends_on = [zitadel_project_member.identity_controller]
}

resource "zitadel_application_oidc" "kubernetes" {
  for_each = toset(["undercloud", "capi-management"])

  org_id                       = local.org_id
  project_id                   = zitadel_project.infrastructure.id
  name                         = "Kubernetes ${each.value}"
  redirect_uris                = ["http://localhost:8000"]
  post_logout_redirect_uris    = ["http://localhost:8000"]
  response_types               = ["OIDC_RESPONSE_TYPE_CODE"]
  grant_types                  = ["OIDC_GRANT_TYPE_AUTHORIZATION_CODE", "OIDC_GRANT_TYPE_REFRESH_TOKEN"]
  app_type                     = "OIDC_APP_TYPE_NATIVE"
  auth_method_type             = "OIDC_AUTH_METHOD_TYPE_NONE"
  version                      = "OIDC_VERSION_1_0"
  access_token_type            = "OIDC_TOKEN_TYPE_BEARER"
  access_token_role_assertion  = true
  id_token_role_assertion      = true
  id_token_userinfo_assertion  = true
  dev_mode                     = false
  additional_origins           = []
  skip_native_app_success_page = true
}

output "organization_id" {
  value = local.org_id
}

output "forgejo_client_id" {
  value     = zitadel_application_oidc.web["forgejo"].client_id
  sensitive = true
}

output "forgejo_client_secret" {
  value     = zitadel_application_oidc.web["forgejo"].client_secret
  sensitive = true
}

output "infrastructure_project_id" {
  value = zitadel_project.infrastructure.id
}

output "role_claim" {
  value = "urn:zitadel:iam:org:project:${zitadel_project.infrastructure.id}:roles"
}

output "grafana_client_id" {
  value     = zitadel_application_oidc.web["grafana"].client_id
  sensitive = true
}

output "grafana_client_secret" {
  value     = zitadel_application_oidc.web["grafana"].client_secret
  sensitive = true
}

output "openstack_client_id" {
  value     = zitadel_application_oidc.web["openstack"].client_id
  sensitive = true
}

output "openstack_client_secret" {
  value     = zitadel_application_oidc.web["openstack"].client_secret
  sensitive = true
}

output "sftpgo_client_id" {
  value     = zitadel_application_oidc.web["sftpgo"].client_id
  sensitive = true
}

output "sftpgo_client_secret" {
  value     = zitadel_application_oidc.web["sftpgo"].client_secret
  sensitive = true
}

output "navidrome_client_id" {
  value     = zitadel_application_oidc.web["navidrome"].client_id
  sensitive = true
}

output "navidrome_client_secret" {
  value     = zitadel_application_oidc.web["navidrome"].client_secret
  sensitive = true
}

output "audiomuse_client_id" {
  value     = zitadel_application_oidc.web["audiomuse"].client_id
  sensitive = true
}

output "audiomuse_client_secret" {
  value     = zitadel_application_oidc.web["audiomuse"].client_secret
  sensitive = true
}

output "wallos_client_id" {
  value     = zitadel_application_oidc.wallos.client_id
  sensitive = true
}

output "wallos_client_secret" {
  value     = zitadel_application_oidc.wallos.client_secret
  sensitive = true
}

output "undercloud_kubernetes_client_id" {
  value     = zitadel_application_oidc.kubernetes["undercloud"].client_id
  sensitive = true
}

output "capi_management_kubernetes_client_id" {
  value     = zitadel_application_oidc.kubernetes["capi-management"].client_id
  sensitive = true
}

output "identity_controller_key" {
  value     = zitadel_machine_key.identity_controller.key_details
  sensitive = true
}

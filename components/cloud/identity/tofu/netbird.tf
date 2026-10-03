resource "zitadel_project" "netbird" {
  org_id                 = local.org_id
  name                   = "NetBird"
  project_role_assertion = true
  project_role_check     = true
  has_project_check      = true
}

resource "zitadel_project_role" "netbird_services" {
  org_id       = local.org_id
  project_id   = zitadel_project.netbird.id
  role_key     = "netbird-services"
  display_name = "Private services"
  group        = "netbird"
}

resource "zitadel_user_grant" "netbird_owner" {
  org_id     = local.org_id
  project_id = zitadel_project.netbird.id
  user_id    = local.breakglass_user_id
  role_keys  = [zitadel_project_role.netbird_services.role_key]
}

resource "zitadel_user_grant" "netbird_funforgiven" {
  org_id     = local.org_id
  project_id = zitadel_project.netbird.id
  # The owner's everyday account, also used by the Matrix project.
  user_id   = "385540008259371450"
  role_keys = [zitadel_project_role.netbird_services.role_key]
}

resource "zitadel_application_oidc" "netbird" {
  org_id                      = local.org_id
  project_id                  = zitadel_project.netbird.id
  name                        = "NetBird"
  redirect_uris               = ["https://netbird.fahrican.com/oauth2/callback"]
  response_types              = ["OIDC_RESPONSE_TYPE_CODE"]
  grant_types                 = ["OIDC_GRANT_TYPE_AUTHORIZATION_CODE", "OIDC_GRANT_TYPE_REFRESH_TOKEN"]
  app_type                    = "OIDC_APP_TYPE_WEB"
  auth_method_type            = "OIDC_AUTH_METHOD_TYPE_BASIC"
  version                     = "OIDC_VERSION_1_0"
  access_token_type           = "OIDC_TOKEN_TYPE_BEARER"
  access_token_role_assertion = true
  id_token_role_assertion     = true
  id_token_userinfo_assertion = true
  dev_mode                    = false
}

output "netbird_client_id" {
  value     = zitadel_application_oidc.netbird.client_id
  sensitive = true
}

output "netbird_client_secret" {
  value     = zitadel_application_oidc.netbird.client_secret
  sensitive = true
}

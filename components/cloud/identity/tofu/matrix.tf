resource "zitadel_project" "matrix" {
  org_id                 = local.org_id
  name                   = "Matrix"
  project_role_assertion = true
  project_role_check     = true
  has_project_check      = true
}

resource "zitadel_project_role" "matrix_member" {
  org_id       = local.org_id
  project_id   = zitadel_project.matrix.id
  role_key     = "matrix-member"
  display_name = "Matrix member"
  group        = "matrix"
}

resource "zitadel_user_grant" "matrix_owner" {
  org_id     = local.org_id
  project_id = zitadel_project.matrix.id
  user_id    = local.breakglass_user_id
  role_keys  = [zitadel_project_role.matrix_member.role_key]
}

resource "zitadel_user_grant" "matrix_funforgiven" {
  org_id     = local.org_id
  project_id = zitadel_project.matrix.id
  # The owner's account, resolved through the private ZITADEL API.
  user_id   = "385540008259371450"
  role_keys = [zitadel_project_role.matrix_member.role_key]
}

resource "zitadel_application_oidc" "matrix" {
  org_id                      = local.org_id
  project_id                  = zitadel_project.matrix.id
  name                        = "Matrix Authentication Service"
  redirect_uris               = ["https://matrix-auth.fahrican.com/upstream/callback/01HFVBY12TMNTYTBV8W921M5FA"]
  post_logout_redirect_uris   = ["https://element.fahrican.com/"]
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

output "matrix_client_id" {
  value     = zitadel_application_oidc.matrix.client_id
  sensitive = true
}

output "matrix_client_secret" {
  value     = zitadel_application_oidc.matrix.client_secret
  sensitive = true
}

output "matrix_project_id" {
  value = zitadel_project.matrix.id
}

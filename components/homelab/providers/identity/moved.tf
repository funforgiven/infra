# Address renames from before the state migration. They are no-ops once the
# state uses the new addresses; delete this file after the first clean plan
# on migrated state (docs/rollout.md).
# Keeps the Kubernetes OAuth client ID stable under the renamed key.
moved {
  from = zitadel_application_oidc.kubernetes["undercloud"]
  to   = zitadel_application_oidc.kubernetes["homelab"]
}

# Matrix and NetBird projects folded into the shared app resources.
moved {
  from = zitadel_project.matrix
  to   = zitadel_project.app["matrix"]
}

moved {
  from = zitadel_project.netbird
  to   = zitadel_project.app["netbird"]
}

moved {
  from = zitadel_project_role.matrix_member
  to   = zitadel_project_role.app["matrix"]
}

moved {
  from = zitadel_project_role.netbird_services
  to   = zitadel_project_role.app["netbird"]
}

moved {
  from = zitadel_user_grant.matrix_owner
  to   = zitadel_user_grant.app["matrix-breakglass"]
}

moved {
  from = zitadel_user_grant.matrix_funforgiven
  to   = zitadel_user_grant.app["matrix-owner"]
}

moved {
  from = zitadel_user_grant.netbird_owner
  to   = zitadel_user_grant.app["netbird-breakglass"]
}

moved {
  from = zitadel_user_grant.netbird_funforgiven
  to   = zitadel_user_grant.app["netbird-owner"]
}

moved {
  from = zitadel_application_oidc.matrix
  to   = zitadel_application_oidc.web["matrix"]
}

moved {
  from = zitadel_application_oidc.netbird
  to   = zitadel_application_oidc.web["netbird"]
}

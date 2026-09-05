# Reconcile security defaults through the supported application-settings model.
# Never print settings: they can contain tokens and integration credentials.
ApplicationSetting.current.update!(
  signup_enabled: false,
  require_admin_approval_after_user_signup: true,
  default_project_visibility: 0,
  default_group_visibility: 0,
  default_snippet_visibility: 0,
  restricted_visibility_levels: [10, 20],
  password_authentication_enabled_for_git: false,
  require_two_factor_authentication: true,
  two_factor_grace_period: 24,
  allow_local_requests_from_web_hooks_and_services: false,
  allow_local_requests_from_system_hooks: false,
  shared_runners_enabled: false,
  usage_ping_enabled: false
)

mock_provider "google" {
  mock_resource "google_compute_network" {
    defaults = { id = "projects/test-mail-12345/global/networks/mail" }
  }
  mock_resource "google_service_account" {
    defaults = {
      email  = "mail@test-mail-12345.iam.gserviceaccount.com"
      member = "serviceAccount:mail@test-mail-12345.iam.gserviceaccount.com"
    }
  }
}

override_data {
  target = data.google_project.mail
  values = { billing_account = "AAAAAA-BBBBBB-CCCCCC", number = "123456789012" }
}

variables {
  project_id   = "test-mail-12345"
  alert_email  = "operator@example.net"
  budget_units = 40
}

run "foundation_is_private_and_waits_for_restore" {
  command = plan
  assert {
    condition = (
      google_compute_instance.mail.metadata["mail-runtime"] == "false" &&
      google_compute_instance.mail.metadata["mail-monitor"] == "false" &&
      length(google_monitoring_uptime_check_config.jmap) == 0 &&
      google_sql_database_instance.mail.settings[0].tier == "db-f1-micro" &&
      !google_sql_database_instance.mail.settings[0].ip_configuration[0].ipv4_enabled &&
      google_sql_database_instance.mail.settings[0].backup_configuration[0].point_in_time_recovery_enabled &&
      google_storage_bucket.blobs.versioning[0].enabled
    )
    error_message = "The migration foundation must keep the database private, preserve recovery and defer mail activation."
  }
}

run "delivery_checks_require_a_running_server" {
  command = plan
  variables {
    monitor_delivery = true
  }
  expect_failures = [var.monitor_delivery]
}

run "live_delivery_has_external_monitoring" {
  command = plan
  variables {
    enable_runtime   = true
    monitor_delivery = true
  }
  assert {
    condition     = google_monitoring_alert_policy.operations.enabled && length(google_monitoring_alert_policy.availability) == 1 && google_monitoring_uptime_check_config.jmap[0].http_check[0].validate_ssl
    error_message = "Live mail needs both the external TLS check and application health alerts."
  }
}

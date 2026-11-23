resource "google_monitoring_notification_channel" "operator" {
  display_name = "Mail operator"
  type         = "email"
  labels       = { email_address = var.alert_email }
  depends_on   = [google_project_service.mail]
}

resource "google_monitoring_metric_descriptor" "mail" {
  type         = "custom.googleapis.com/stalwart/operation"
  metric_kind  = "GAUGE"
  value_type   = "DOUBLE"
  display_name = "Stalwart mail operations"
  description  = "Mail service, queue, certificate and recovery checks sampled by the mail VM"
  labels {
    key        = "measure"
    value_type = "STRING"
  }
  depends_on = [google_project_service.mail]
}

resource "google_monitoring_alert_policy" "operations" {
  display_name          = "Stalwart mail health and recovery"
  enabled               = var.monitor_delivery
  combiner              = "OR"
  notification_channels = [google_monitoring_notification_channel.operator.name]

  dynamic "conditions" {
    for_each = {
      ServiceHealthy              = ["COMPARISON_LT", 1]
      InboundAgeSeconds           = ["COMPARISON_GT", 3600]
      BackupAgeSeconds            = ["COMPARISON_GT", 90000]
      RestoreAgeSeconds           = ["COMPARISON_GT", 691200]
      OldestQueuedSeconds         = ["COMPARISON_GT", 3600]
      CertificateSecondsRemaining = ["COMPARISON_LT", 1209600]
    }
    content {
      display_name = conditions.key
      condition_threshold {
        filter          = "resource.type = \"global\" AND metric.type = \"${google_monitoring_metric_descriptor.mail.type}\" AND metric.labels.measure = \"${conditions.key}\""
        comparison      = conditions.value[0]
        threshold_value = conditions.value[1]
        duration        = "600s"
        aggregations {
          alignment_period   = "300s"
          per_series_aligner = "ALIGN_MEAN"
        }
      }
    }
  }
}

resource "google_monitoring_uptime_check_config" "jmap" {
  count        = var.monitor_delivery ? 1 : 0
  display_name = "Public Stalwart JMAP discovery"
  timeout      = "10s"
  period       = "300s"
  monitored_resource {
    type   = "uptime_url"
    labels = { project_id = var.project_id, host = "mail.fahrican.com" }
  }
  http_check {
    path         = "/jmap/session"
    port         = 443
    use_ssl      = true
    validate_ssl = true
  }
  content_matchers {
    content = "urn:ietf:params:jmap:mail"
    matcher = "CONTAINS_STRING"
  }
  depends_on = [google_project_service.mail]
}

resource "google_monitoring_alert_policy" "availability" {
  count                 = var.monitor_delivery ? 1 : 0
  display_name          = "Mail public endpoint or telemetry unavailable"
  combiner              = "OR"
  notification_channels = [google_monitoring_notification_channel.operator.name]
  conditions {
    display_name = "Public JMAP check failing"
    condition_threshold {
      filter          = "resource.type = \"uptime_url\" AND metric.type = \"monitoring.googleapis.com/uptime_check/check_passed\" AND metric.labels.check_id = \"${google_monitoring_uptime_check_config.jmap[0].uptime_check_id}\""
      comparison      = "COMPARISON_LT"
      threshold_value = 1
      duration        = "600s"
      aggregations {
        alignment_period   = "300s"
        per_series_aligner = "ALIGN_FRACTION_TRUE"
      }
    }
  }
  conditions {
    display_name = "Mail health telemetry missing"
    condition_absent {
      filter   = "resource.type = \"global\" AND metric.type = \"${google_monitoring_metric_descriptor.mail.type}\" AND metric.labels.measure = \"ServiceHealthy\""
      duration = "900s"
    }
  }
}

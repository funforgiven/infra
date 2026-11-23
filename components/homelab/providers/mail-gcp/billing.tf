variable "budget_units" {
  description = "Monthly gross budget in whole units of the linked billing account currency (USD 40 or its local equivalent)"
  type        = number
  validation {
    condition     = var.budget_units > 0 && var.budget_units == floor(var.budget_units)
    error_message = "Enter a positive whole amount in the account's billing currency."
  }
}

data "google_project" "mail" {
  project_id = var.project_id
}

resource "google_project_service" "budgets" {
  service            = "billingbudgets.googleapis.com"
  disable_on_destroy = false
}

resource "google_billing_budget" "mail" {
  billing_account = data.google_project.mail.billing_account
  display_name    = "Mail monthly cost before credits"
  budget_filter {
    projects               = ["projects/${data.google_project.mail.number}"]
    credit_types_treatment = "EXCLUDE_ALL_CREDITS"
    calendar_period        = "MONTH"
  }
  amount {
    specified_amount {
      units = tostring(var.budget_units)
    }
  }
  dynamic "threshold_rules" {
    for_each = toset(["0.5", "0.8", "1"])
    content {
      threshold_percent = tonumber(threshold_rules.value)
    }
  }
  all_updates_rule {
    monitoring_notification_channels = [google_monitoring_notification_channel.operator.name]
    disable_default_iam_recipients   = false
  }
  depends_on = [google_project_service.budgets]
}

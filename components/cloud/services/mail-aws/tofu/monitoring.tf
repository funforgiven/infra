resource "aws_sns_topic" "mail_alerts" {
  name = "stalwart-mail-alerts"
}

resource "aws_sns_topic_subscription" "mail_alerts" {
  topic_arn = aws_sns_topic.mail_alerts.arn
  protocol  = "email"
  endpoint  = "fahricanelidemir@gmail.com"
}

# EC2 stops publishing an old instance dimension while create-before-destroy
# replacement changes IDs. Absence is not a failed status check; only an
# observed StatusCheckFailed sample should notify.
resource "aws_cloudwatch_metric_alarm" "instance_status" {
  alarm_name          = "stalwart-mail-instance-status"
  alarm_description   = "The Stalwart EC2 instance failed an AWS status check"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 2
  metric_name         = "StatusCheckFailed"
  namespace           = "AWS/EC2"
  period              = 60
  statistic           = "Maximum"
  threshold           = 1
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.mail_alerts.arn]
  ok_actions          = [aws_sns_topic.mail_alerts.arn]

  dimensions = {
    InstanceId = aws_instance.mail.id
  }
}

resource "aws_cloudwatch_metric_alarm" "database_cpu" {
  alarm_name          = "stalwart-mail-database-cpu"
  alarm_description   = "The Stalwart RDS instance has sustained high CPU"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 3
  metric_name         = "CPUUtilization"
  namespace           = "AWS/RDS"
  period              = 300
  statistic           = "Average"
  threshold           = 80
  treat_missing_data  = "breaching"
  alarm_actions       = [aws_sns_topic.mail_alerts.arn]
  ok_actions          = [aws_sns_topic.mail_alerts.arn]

  dimensions = {
    DBInstanceIdentifier = aws_db_instance.mail.identifier
  }
}

resource "aws_cloudwatch_metric_alarm" "database_storage" {
  alarm_name          = "stalwart-mail-database-free-storage"
  alarm_description   = "The Stalwart RDS instance has less than 5 GiB free"
  comparison_operator = "LessThanThreshold"
  evaluation_periods  = 3
  metric_name         = "FreeStorageSpace"
  namespace           = "AWS/RDS"
  period              = 300
  statistic           = "Average"
  threshold           = 5368709120
  treat_missing_data  = "breaching"
  alarm_actions       = [aws_sns_topic.mail_alerts.arn]
  ok_actions          = [aws_sns_topic.mail_alerts.arn]

  dimensions = {
    DBInstanceIdentifier = aws_db_instance.mail.identifier
  }
}

locals {
  mail_health_alarms = {
    service = {
      metric      = "ServiceHealthy", comparison = "LessThanThreshold", threshold = 1
      description = "Stalwart, authenticated JMAP, incoming SMTP/TLS, or queue inspection failed, or health telemetry stopped"
    }
    inbound_delivery = {
      metric      = "InboundAgeSeconds", comparison = "GreaterThanThreshold", threshold = 3600
      description = "No verified Resend-to-public-MX-to-authenticated-JMAP delivery with an intact attachment within one hour"
    }
    backup = {
      metric      = "BackupAgeSeconds", comparison = "GreaterThanThreshold", threshold = 90000
      description = "No successful encrypted offsite mailbox backup within 25 hours"
    }
    restore = {
      metric      = "RestoreAgeSeconds", comparison = "GreaterThanThreshold", threshold = 691200
      description = "No verified download and integrity check of the offsite backup within eight days"
    }
    disk = {
      metric      = "RootFreeBytes", comparison = "LessThanThreshold", threshold = 5368709120
      description = "Mail host has less than 5 GiB free for backup staging and runtime operation"
    }
    certificate = {
      metric      = "CertificateSecondsRemaining", comparison = "LessThanThreshold", threshold = 1814400
      description = "Mail TLS certificate expires within 21 days"
    }
    queue_age = {
      metric      = "OldestQueuedSeconds", comparison = "GreaterThanThreshold", threshold = 3600
      description = "A mail delivery has waited more than one hour, excluding automatic reports' initial scheduled delay"
    }
    queue_size = {
      metric      = "QueueMessages", comparison = "GreaterThanThreshold", threshold = 100
      description = "More than 100 messages are awaiting delivery"
    }
  }
}

resource "aws_cloudwatch_metric_alarm" "mail_health" {
  for_each            = local.mail_health_alarms
  alarm_name          = "stalwart-mail-${each.key}"
  alarm_description   = each.value.description
  comparison_operator = each.value.comparison
  evaluation_periods  = 3
  metric_name         = each.value.metric
  namespace           = "Fahrican/Mail"
  period              = 300
  statistic           = "Average"
  threshold           = each.value.threshold
  treat_missing_data  = "breaching"
  alarm_actions       = [aws_sns_topic.mail_alerts.arn]
  ok_actions          = [aws_sns_topic.mail_alerts.arn]
  dimensions          = { Service = local.service_name }
}

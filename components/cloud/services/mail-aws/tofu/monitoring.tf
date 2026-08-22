resource "aws_sns_topic" "mail_alerts" {
  name = "stalwart-mail-alerts"
}

resource "aws_sns_topic_subscription" "mail_alerts" {
  topic_arn = aws_sns_topic.mail_alerts.arn
  protocol  = "email"
  endpoint  = "fahricanelidemir@gmail.com"
}

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
  treat_missing_data  = "breaching"
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

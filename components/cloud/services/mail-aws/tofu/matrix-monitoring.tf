variable "enable_matrix_monitoring" {
  type        = bool
  default     = false
  description = "Enable independent Matrix checks after public endpoint enrollment"
}

data "archive_file" "matrix_probe" {
  count       = var.enable_matrix_monitoring ? 1 : 0
  type        = "zip"
  source_file = "${path.module}/../../matrix/outside_check.py"
  output_path = "/tmp/fahrican-matrix-probe.zip"
}

resource "aws_secretsmanager_secret" "matrix_heartbeat" {
  count                   = var.enable_matrix_monitoring ? 1 : 0
  name                    = "fahrican/stalwart/matrix-heartbeat"
  recovery_window_in_days = 30
}

resource "aws_iam_role" "matrix_probe" {
  count = var.enable_matrix_monitoring ? 1 : 0
  name  = "stalwart-matrix-probe"
  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Action = "sts:AssumeRole", Principal = { Service = "lambda.amazonaws.com" } }]
  })
}

resource "aws_cloudwatch_log_group" "matrix_probe" {
  count             = var.enable_matrix_monitoring ? 1 : 0
  name              = "/aws/lambda/stalwart-matrix-probe"
  retention_in_days = 14
}

resource "aws_iam_role_policy" "matrix_probe" {
  count = var.enable_matrix_monitoring ? 1 : 0
  name  = "matrix-probe"
  role  = aws_iam_role.matrix_probe[0].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = "cloudwatch:PutMetricData", Resource = "*", Condition = { StringEquals = { "cloudwatch:namespace" = "Fahrican/Matrix" } } },
      { Effect = "Allow", Action = "secretsmanager:GetSecretValue", Resource = aws_secretsmanager_secret.matrix_heartbeat[0].arn },
      { Effect = "Allow", Action = ["logs:CreateLogStream", "logs:PutLogEvents"], Resource = "${aws_cloudwatch_log_group.matrix_probe[0].arn}:*" },
    ]
  })
}

resource "aws_lambda_function" "matrix_probe" {
  count                          = var.enable_matrix_monitoring ? 1 : 0
  function_name                  = "stalwart-matrix-probe"
  role                           = aws_iam_role.matrix_probe[0].arn
  filename                       = data.archive_file.matrix_probe[0].output_path
  source_code_hash               = data.archive_file.matrix_probe[0].output_base64sha256
  runtime                        = "python3.13"
  architectures                  = ["arm64"]
  handler                        = "outside_check.handler"
  timeout                        = 45
  memory_size                    = 128
  reserved_concurrent_executions = 2
  environment {
    variables = { HEARTBEAT_SECRET_ARN = aws_secretsmanager_secret.matrix_heartbeat[0].arn }
  }
  depends_on = [aws_iam_role_policy.matrix_probe]
}

resource "aws_lambda_function_url" "matrix_heartbeat" {
  count              = var.enable_matrix_monitoring ? 1 : 0
  function_name      = aws_lambda_function.matrix_probe[0].function_name
  authorization_type = "NONE"
}

# Public transport is authenticated inside the handler with a Secret Manager token.
resource "aws_lambda_permission" "matrix_heartbeat_url" {
  count                  = var.enable_matrix_monitoring ? 1 : 0
  statement_id           = "HeartbeatTransport"
  action                 = "lambda:InvokeFunctionUrl"
  function_name          = aws_lambda_function.matrix_probe[0].function_name
  principal              = "*"
  function_url_auth_type = "NONE"
}

resource "aws_lambda_permission" "matrix_heartbeat_invoke" {
  count                    = var.enable_matrix_monitoring ? 1 : 0
  statement_id             = "HeartbeatInvoke"
  action                   = "lambda:InvokeFunction"
  function_name            = aws_lambda_function.matrix_probe[0].function_name
  principal                = "*"
  invoked_via_function_url = true
}

resource "aws_cloudwatch_event_rule" "matrix_probe" {
  count               = var.enable_matrix_monitoring ? 1 : 0
  name                = "stalwart-matrix-probe"
  schedule_expression = "rate(1 minute)"
}

resource "aws_cloudwatch_event_target" "matrix_probe" {
  count = var.enable_matrix_monitoring ? 1 : 0
  rule  = aws_cloudwatch_event_rule.matrix_probe[0].name
  arn   = aws_lambda_function.matrix_probe[0].arn
}

resource "aws_lambda_permission" "matrix_probe_schedule" {
  count         = var.enable_matrix_monitoring ? 1 : 0
  statement_id  = "ScheduledAvailabilityCheck"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.matrix_probe[0].function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.matrix_probe[0].arn
}

resource "aws_cloudwatch_metric_alarm" "matrix_public" {
  count               = var.enable_matrix_monitoring ? 1 : 0
  alarm_name          = "stalwart-matrix-public-unavailable"
  namespace           = "Fahrican/Matrix"
  metric_name         = "PublicAvailability"
  statistic           = "Minimum"
  period              = 60
  evaluation_periods  = 3
  threshold           = 1
  comparison_operator = "LessThanThreshold"
  treat_missing_data  = "breaching"
  alarm_actions       = [aws_sns_topic.mail_alerts.arn]
  ok_actions          = [aws_sns_topic.mail_alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "matrix_delivery" {
  count               = var.enable_matrix_monitoring ? 1 : 0
  alarm_name          = "stalwart-matrix-delivery-stalled"
  namespace           = "Fahrican/Matrix"
  metric_name         = "DeliveryHeartbeat"
  statistic           = "Sum"
  period              = 60
  evaluation_periods  = 5
  threshold           = 1
  comparison_operator = "LessThanThreshold"
  treat_missing_data  = "breaching"
  alarm_actions       = [aws_sns_topic.mail_alerts.arn]
  ok_actions          = [aws_sns_topic.mail_alerts.arn]
}

output "matrix_heartbeat_url" {
  value = try(aws_lambda_function_url.matrix_heartbeat[0].function_url, "")
}

output "matrix_heartbeat_secret_arn" {
  value = try(aws_secretsmanager_secret.matrix_heartbeat[0].arn, "")
}

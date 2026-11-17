output "ipv4_address" {
  description = "Stable public mail address (EIP)"
  value       = var.mail_enabled ? aws_eip.mail.public_ip : null
}

output "instance_id" {
  description = "EC2 instance identifier used for Session Manager access"
  value       = var.mail_enabled ? aws_instance.mail.id : null
}

output "database_endpoint" {
  description = "Private managed PostgreSQL endpoint"
  value       = var.mail_enabled ? aws_db_instance.mail.endpoint : null
}

output "blob_bucket" {
  description = "Versioned S3 bucket storing Stalwart blobs"
  value       = aws_s3_bucket.mail.id
}

output "mail_enabled" {
  description = "Whether mail compute, database and public endpoint are enabled"
  value       = var.mail_enabled
}

output "final_snapshot_identifier" {
  description = "Requested final RDS snapshot name; verify it is available after pausing and use it to resume"
  value       = var.final_snapshot_identifier
}

output "admin_secret_arn" {
  description = "Secret container populated by the mail instance during bootstrap"
  value       = aws_secretsmanager_secret.admin.arn
}

output "mailbox_secret_arn" {
  description = "Secret container populated by the mail instance during bootstrap"
  value       = aws_secretsmanager_secret.mailbox.arn
}

output "resend_secret_arn" {
  description = "Secret container populated through the no-echo runtime enrollment"
  value       = aws_secretsmanager_secret.resend.arn
}

output "alert_topic_arn" {
  description = "Independent AWS health notification topic"
  value       = aws_sns_topic.mail_alerts.arn
}

output "ipv4_address" {
  description = "Stable AWS address prepared for the deliberate mail DNS cutover"
  value       = aws_eip.mail.public_ip
}

output "instance_id" {
  description = "EC2 instance identifier used for Session Manager access"
  value       = aws_instance.mail.id
}

output "database_endpoint" {
  description = "Private managed PostgreSQL endpoint"
  value       = aws_db_instance.mail.endpoint
}

output "blob_bucket" {
  description = "Versioned S3 bucket storing Stalwart blobs"
  value       = aws_s3_bucket.mail.id
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

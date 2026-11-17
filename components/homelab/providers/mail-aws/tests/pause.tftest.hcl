mock_provider "aws" {
  mock_data "aws_iam_policy_document" {
    defaults = { json = "{\"Version\":\"2012-10-17\",\"Statement\":[]}" }
  }
  mock_resource "aws_secretsmanager_secret" {
    defaults = { arn = "arn:aws:secretsmanager:eu-central-1:123456789012:secret:fahrican/stalwart/test-ABCDEF" }
  }
  mock_resource "aws_sns_topic" {
    defaults = { arn = "arn:aws:sns:eu-central-1:123456789012:stalwart-mail-alerts" }
  }
  mock_resource "aws_db_instance" {
    defaults = {
      master_user_secret = [{
        secret_arn    = "arn:aws:secretsmanager:eu-central-1:123456789012:secret:rds!db-test-ABCDEF"
        kms_key_id    = "arn:aws:kms:eu-central-1:123456789012:key/12345678-1234-1234-1234-123456789012"
        secret_status = "active"
      }]
    }
  }
}

override_data {
  target = data.aws_availability_zones.available
  values = { names = ["eu-central-1a", "eu-central-1b"] }
}

override_data {
  target = data.aws_caller_identity.current
  values = { account_id = "123456789012" }
}

override_data {
  target = data.aws_kms_key.rds_storage
  values = { arn = "arn:aws:kms:eu-central-1:123456789012:key/12345678-1234-1234-1234-123456789012" }
}

variables {
  mail_enabled    = true
  source_revision = "533fb1c17c45a359a706db9bf537167239651fdd"
  nixos_ami_id    = "ami-019a83797574d9161"
}

run "paused_retains_recovery_without_compute" {
  command = plan

  variables {
    mail_enabled          = false
    allow_runtime_destroy = true
  }

  assert {
    condition     = aws_instance.mail == null && aws_db_instance.mail == null && aws_eip.mail == null && terraform_data.mail_ready == null
    error_message = "Paused mail must have no EC2, RDS, public IPv4 address or readiness provisioner."
  }

  assert {
    condition     = aws_cloudwatch_metric_alarm.instance_status == null && aws_cloudwatch_metric_alarm.database_cpu == null && aws_cloudwatch_metric_alarm.database_storage == null && length(aws_cloudwatch_metric_alarm.mail_health) == 0
    error_message = "Paused mail must not retain billed CloudWatch alarms."
  }

  assert {
    condition     = aws_s3_bucket.mail.bucket == "fahrican-stalwart-123456789012-eu-central-1" && aws_s3_bucket.mail.force_destroy == false && aws_s3_bucket_versioning.mail.versioning_configuration[0].status == "Enabled"
    error_message = "Paused mail must retain the original protected, versioned blob bucket."
  }

  assert {
    condition     = aws_secretsmanager_secret.admin != null && aws_secretsmanager_secret.mailbox != null && aws_secretsmanager_secret.backup != null && aws_secretsmanager_secret.resend != null && aws_secretsmanager_secret.vpn != null && aws_secretsmanager_secret.canary != null
    error_message = "Paused mail must retain all recovery credentials."
  }

  assert {
    condition     = output.instance_id == null && output.ipv4_address == null && output.database_endpoint == null
    error_message = "Paused outputs must not advertise retired endpoints."
  }
}

run "pause_preparation_requires_final_snapshot" {
  command = plan

  variables {
    allow_runtime_destroy     = true
    final_snapshot_identifier = "stalwart-mail-paused-test"
  }

  assert {
    condition     = aws_db_instance.mail.skip_final_snapshot == false && aws_db_instance.mail.final_snapshot_identifier == "stalwart-mail-paused-test" && aws_db_instance.mail.deletion_protection == false && aws_db_instance.mail.apply_immediately == true
    error_message = "Pause preparation must clear deletion protection immediately and preserve a named final snapshot."
  }
}

run "resume_uses_existing_database" {
  command = plan

  variables {
    restore_snapshot_identifier = "stalwart-mail-paused-test"
  }

  assert {
    condition     = aws_db_instance.mail.snapshot_identifier == "stalwart-mail-paused-test" && aws_db_instance.mail.deletion_protection == true && aws_db_instance.mail.skip_final_snapshot == false
    error_message = "Resuming must restore the selected snapshot and restore database deletion protection."
  }
}

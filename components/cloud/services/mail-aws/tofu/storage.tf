data "aws_caller_identity" "current" {}

data "aws_kms_key" "rds_storage" {
  key_id = "alias/aws/rds"
}

resource "aws_db_subnet_group" "mail" {
  name       = "stalwart-mail"
  subnet_ids = [for subnet in aws_subnet.database : subnet.id]
  tags       = { Name = "stalwart-mail" }
}

resource "aws_db_instance" "mail" {
  identifier = "stalwart-mail"

  engine         = "postgres"
  engine_version = "17.10"
  instance_class = "db.t4g.micro"

  allocated_storage     = 20
  max_allocated_storage = 100
  storage_type          = "gp3"
  storage_encrypted     = true
  # RDS records the canonical key ARN. Supplying the equivalent alias ARN
  # creates a perpetual ForceNew diff in the AWS provider.
  kms_key_id = data.aws_kms_key.rds_storage.arn

  db_name                     = "stalwart"
  username                    = "stalwart"
  manage_master_user_password = true
  port                        = 5432

  db_subnet_group_name   = aws_db_subnet_group.mail.name
  vpc_security_group_ids = [aws_security_group.database.id]
  publicly_accessible    = false
  multi_az               = false

  backup_retention_period = 14
  backup_window           = "01:00-02:00"
  maintenance_window      = "sun:02:30-sun:03:30"
  copy_tags_to_snapshot   = true

  auto_minor_version_upgrade  = true
  allow_major_version_upgrade = false
  deletion_protection         = true
  skip_final_snapshot         = false
  final_snapshot_identifier   = "stalwart-mail-final"
  apply_immediately           = false

  performance_insights_enabled = false
  monitoring_interval          = 0

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_security_group" "restore_qualification" {
  count = var.enable_restore_qualification ? 1 : 0

  name        = "stalwart-mail-restore-qualification"
  description = "Temporary isolated PostgreSQL restore target"
  vpc_id      = aws_vpc.mail.id

  ingress {
    description     = "Restore verification from the Stalwart appliance"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.mail.id]
  }

  tags = { Name = "stalwart-mail-restore-qualification" }
}

resource "aws_db_instance" "restore_qualification" {
  count = var.enable_restore_qualification ? 1 : 0

  identifier = "stalwart-mail-restore-qualification"

  engine         = "postgres"
  engine_version = "17.10"
  instance_class = "db.t4g.micro"

  allocated_storage = 20
  storage_type      = "gp3"
  storage_encrypted = true
  kms_key_id        = data.aws_kms_key.rds_storage.arn

  db_name                     = "stalwart"
  username                    = "stalwart_restore"
  manage_master_user_password = true
  port                        = 5432

  db_subnet_group_name   = aws_db_subnet_group.mail.name
  vpc_security_group_ids = [aws_security_group.restore_qualification[0].id]
  publicly_accessible    = false
  multi_az               = false

  backup_retention_period = 0
  auto_minor_version_upgrade = true
  deletion_protection         = false
  skip_final_snapshot         = true
  apply_immediately           = true

  performance_insights_enabled = false
  monitoring_interval          = 0

  tags = {
    Name      = "stalwart-mail-restore-qualification"
    Ephemeral = "true"
  }
}

resource "aws_s3_bucket" "mail" {
  bucket        = "fahrican-stalwart-${data.aws_caller_identity.current.account_id}-eu-central-1"
  force_destroy = false

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_s3_bucket_public_access_block" "mail" {
  bucket = aws_s3_bucket.mail.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "mail" {
  bucket = aws_s3_bucket.mail.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
    bucket_key_enabled = false
  }
}

resource "aws_s3_bucket_versioning" "mail" {
  bucket = aws_s3_bucket.mail.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "mail" {
  bucket = aws_s3_bucket.mail.id

  rule {
    id     = "expire-noncurrent-blob-versions"
    status = "Enabled"

    filter {}

    noncurrent_version_expiration {
      noncurrent_days = 90
    }
  }

  depends_on = [aws_s3_bucket_versioning.mail]
}

data "aws_iam_policy_document" "mail_bucket" {
  statement {
    sid    = "DenyInsecureTransport"
    effect = "Deny"

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    actions = ["s3:*"]
    resources = [
      aws_s3_bucket.mail.arn,
      "${aws_s3_bucket.mail.arn}/*",
    ]

    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "mail" {
  bucket = aws_s3_bucket.mail.id
  policy = data.aws_iam_policy_document.mail_bucket.json

  depends_on = [aws_s3_bucket_public_access_block.mail]
}

resource "aws_secretsmanager_secret" "admin" {
  name                    = "fahrican/stalwart/admin"
  description             = "Stalwart administrator password generated on the mail instance"
  recovery_window_in_days = 30

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_secretsmanager_secret" "mailbox" {
  name                    = "fahrican/stalwart/mailbox"
  description             = "Password for fahrican@fahrican.com generated on the mail instance"
  recovery_window_in_days = 30

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_secretsmanager_secret" "resend" {
  name                    = "fahrican/stalwart/resend"
  description             = "Independently revocable Resend sending key enrolled without OpenTofu state"
  recovery_window_in_days = 30

  lifecycle {
    prevent_destroy = true
  }
}

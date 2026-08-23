data "aws_ami" "nixos" {
  owners = ["427812963091"]

  filter {
    name   = "image-id"
    values = [var.nixos_ami_id]
  }

  filter {
    name   = "name"
    values = ["nixos/26.05*"]
  }

  filter {
    name   = "architecture"
    values = ["arm64"]
  }

  filter {
    name   = "root-device-type"
    values = ["ebs"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

data "aws_iam_policy_document" "instance_assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "mail" {
  name               = "stalwart-mail"
  assume_role_policy = data.aws_iam_policy_document.instance_assume_role.json
}

resource "aws_iam_role_policy_attachment" "ssm" {
  role       = aws_iam_role.mail.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

data "aws_iam_policy_document" "mail" {
  statement {
    sid = "MailBlobBucketMetadata"
    actions = [
      "s3:GetBucketLocation",
      "s3:ListBucket",
    ]
    resources = [aws_s3_bucket.mail.arn]
  }

  statement {
    sid = "MailBlobObjects"
    actions = [
      "s3:AbortMultipartUpload",
      "s3:DeleteObject",
      "s3:GetObject",
      "s3:ListMultipartUploadParts",
      "s3:PutObject",
    ]
    resources = ["${aws_s3_bucket.mail.arn}/*"]
  }

  statement {
    sid = "ReadRuntimeCredentials"
    actions = [
      "secretsmanager:DescribeSecret",
      "secretsmanager:GetSecretValue",
    ]
    resources = concat(
      [
        aws_db_instance.mail.master_user_secret[0].secret_arn,
        aws_secretsmanager_secret.admin.arn,
        aws_secretsmanager_secret.mailbox.arn,
        aws_secretsmanager_secret.resend.arn,
      ],
      var.enable_restore_qualification ? [
        aws_db_instance.restore_qualification[0].master_user_secret[0].secret_arn,
      ] : [],
    )
  }

  statement {
    sid     = "PublishGeneratedCredentials"
    actions = ["secretsmanager:PutSecretValue"]
    resources = [
      aws_secretsmanager_secret.admin.arn,
      aws_secretsmanager_secret.mailbox.arn,
    ]
  }
}

resource "aws_iam_role_policy" "mail" {
  name   = "stalwart-mail-runtime"
  role   = aws_iam_role.mail.id
  policy = data.aws_iam_policy_document.mail.json
}

resource "aws_iam_instance_profile" "mail" {
  name = "stalwart-mail"
  role = aws_iam_role.mail.name
}

resource "aws_instance" "mail" {
  ami                  = data.aws_ami.nixos.id
  instance_type        = "t4g.micro"
  availability_zone    = aws_subnet.public.availability_zone
  subnet_id            = aws_subnet.public.id
  iam_instance_profile = aws_iam_instance_profile.mail.name
  vpc_security_group_ids = [
    aws_security_group.mail.id,
  ]

  # The retained EIP is associated immediately after instance creation, but
  # cloud-init starts first. A temporary subnet-assigned address keeps the
  # verified Nix fetch from racing that association; AWS replaces it with the
  # retained EIP as soon as the association converges.
  associate_public_ip_address = true
  source_dest_check           = true
  monitoring                  = false

  metadata_options {
    http_endpoint               = "enabled"
    http_protocol_ipv6          = "disabled"
    http_put_response_hop_limit = 1
    http_tokens                 = "required"
    instance_metadata_tags      = "disabled"
  }

  root_block_device {
    encrypted             = true
    delete_on_termination = true
    volume_size           = 16
    volume_type           = "gp3"
  }

  user_data = templatefile("${path.module}/user-data.sh.tftpl", {
    admin_secret_arn   = aws_secretsmanager_secret.admin.arn
    bucket_name        = aws_s3_bucket.mail.id
    mailbox_secret_arn = aws_secretsmanager_secret.mailbox.arn
    rds_host           = aws_db_instance.mail.address
    rds_secret_arn     = aws_db_instance.mail.master_user_secret[0].secret_arn
    resend_secret_arn  = aws_secretsmanager_secret.resend.arn
    source_revision    = var.source_revision
  })
  user_data_replace_on_change = true

  tags = {
    Name           = "stalwart-mail"
    SourceRevision = var.source_revision
  }

  lifecycle {
    create_before_destroy = true
  }

  depends_on = [
    aws_iam_role_policy.mail,
    aws_iam_role_policy_attachment.ssm,
    aws_route_table_association.public,
  ]
}

resource "aws_eip" "mail" {
  domain = "vpc"

  tags = { Name = "stalwart-mail" }

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_eip_association" "mail" {
  allocation_id = aws_eip.mail.id
  instance_id   = aws_instance.mail.id
}

resource "aws_eip_domain_name" "mail" {
  count = var.enable_reverse_dns ? 1 : 0

  allocation_id = aws_eip.mail.id
  domain_name   = "mail.fahrican.com"
}

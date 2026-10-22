# Identity and boundaries for the mail-aws root. Run with administrator
# credentials; the gitops identity cannot change its own policies or the
# boundaries that cap the roles it manages.
terraform {
  required_version = ">= 1.12.1, < 2.0.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "= 6.58.0"
    }
  }
}

provider "aws" {
  region = "eu-central-1"
}

data "aws_caller_identity" "current" {}

locals {
  account_id = data.aws_caller_identity.current.account_id
  gitops     = "fahrican-mail-gitops"
  policies = {
    (local.gitops)                    = "mail-gitops-policy.json"
    fahrican-matrix-monitoring-gitops = "matrix-monitoring-policy.json"
  }
}

resource "aws_iam_user" "gitops" {
  name = local.gitops
}

resource "aws_iam_policy" "gitops" {
  for_each = local.policies
  name     = each.key
  policy   = replace(file("${path.module}/${each.value}"), "ACCOUNT_ID", local.account_id)
}

resource "aws_iam_user_policy_attachment" "gitops" {
  for_each   = local.policies
  user       = aws_iam_user.gitops.name
  policy_arn = aws_iam_policy.gitops[each.key].arn
}

import {
  to = aws_iam_user.gitops
  id = local.gitops
}

import {
  for_each = local.policies
  to       = aws_iam_policy.gitops[each.key]
  id       = "arn:aws:iam::${local.account_id}:policy/${each.key}"
}

import {
  for_each = local.policies
  to       = aws_iam_user_policy_attachment.gitops[each.key]
  id       = "${local.gitops}/arn:aws:iam::${local.account_id}:policy/${each.key}"
}

# Ceilings for the roles the gitops identity may edit. Its role permissions
# require these boundaries, so it cannot grant a role more than they allow.
resource "aws_iam_policy" "mail_boundary" {
  name = "stalwart-mail-boundary"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "MailBlobs"
        Effect   = "Allow"
        Action   = "s3:*"
        Resource = ["arn:aws:s3:::fahrican-stalwart-${local.account_id}-eu-central-1", "arn:aws:s3:::fahrican-stalwart-${local.account_id}-eu-central-1/*"]
      },
      {
        Sid    = "MailSecrets"
        Effect = "Allow"
        Action = ["secretsmanager:DescribeSecret", "secretsmanager:GetSecretValue", "secretsmanager:PutSecretValue"]
        Resource = [
          "arn:aws:secretsmanager:eu-central-1:${local.account_id}:secret:fahrican/stalwart/*",
          "arn:aws:secretsmanager:eu-central-1:${local.account_id}:secret:rds!db-*",
        ]
      },
      {
        Sid      = "MailMetrics"
        Effect   = "Allow"
        Action   = "cloudwatch:PutMetricData"
        Resource = "*"
      },
      {
        # The actions of AmazonSSMManagedInstanceCore, so a bounded role cannot
        # gain SendCommand or parameter access beyond the SSM agent's needs.
        Sid    = "SessionManagerAgent"
        Effect = "Allow"
        Action = [
          "ssm:DescribeAssociation",
          "ssm:GetDeployablePatchSnapshotForInstance",
          "ssm:GetDocument",
          "ssm:DescribeDocument",
          "ssm:GetManifest",
          "ssm:GetParameter",
          "ssm:GetParameters",
          "ssm:ListAssociations",
          "ssm:ListInstanceAssociations",
          "ssm:PutInventory",
          "ssm:PutComplianceItems",
          "ssm:PutConfigurePackageResult",
          "ssm:UpdateAssociationStatus",
          "ssm:UpdateInstanceAssociationStatus",
          "ssm:UpdateInstanceInformation",
          "ssmmessages:CreateControlChannel",
          "ssmmessages:CreateDataChannel",
          "ssmmessages:OpenControlChannel",
          "ssmmessages:OpenDataChannel",
          "ec2messages:AcknowledgeMessage",
          "ec2messages:DeleteMessage",
          "ec2messages:FailMessage",
          "ec2messages:GetEndpoint",
          "ec2messages:GetMessages",
          "ec2messages:SendReply",
        ]
        Resource = "*"
      },
    ]
  })
}

resource "aws_iam_policy" "matrix_probe_boundary" {
  name = "stalwart-matrix-probe-boundary"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = "cloudwatch:PutMetricData"
        Resource = "*"
      },
      {
        Effect   = "Allow"
        Action   = "secretsmanager:GetSecretValue"
        Resource = "arn:aws:secretsmanager:eu-central-1:${local.account_id}:secret:fahrican/stalwart/matrix-heartbeat-*"
      },
      {
        Effect   = "Allow"
        Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "arn:aws:logs:eu-central-1:${local.account_id}:log-group:/aws/lambda/stalwart-matrix-probe:*"
      },
    ]
  })
}

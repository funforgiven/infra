terraform {
  required_version = ">= 1.12.1, < 1.13.0"

  required_providers {
    archive = {
      source  = "hashicorp/archive"
      version = "= 2.7.1"
    }
    aws = {
      source  = "hashicorp/aws"
      version = "= 6.58.0"
    }
  }
}

provider "aws" {
  region = "eu-central-1"

  default_tags {
    tags = local.tags
  }
}

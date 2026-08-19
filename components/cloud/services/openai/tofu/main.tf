terraform {
  required_version = ">= 1.12.1, < 1.13.0"

  required_providers {
    openai = {
      source  = "openai/openai"
      version = "= 1.1.0"
    }
  }
}

provider "openai" {}

locals {
  project_name         = "fahrican-hermes-production"
  service_account_name = "fahrican-hermes-production-service-account"
  access_group_name    = "fahrican-hermes-production-access"
  runtime_permissions  = ["api.responses.write"]
}

resource "openai_project" "hermes" {
  name = local.project_name
}

resource "openai_project_service_account" "hermes" {
  project_id = openai_project.hermes.project_id
  name       = local.service_account_name
}

resource "openai_project_role" "hermes" {
  project_id  = openai_project.hermes.project_id
  role_name   = "Hermes response writer"
  description = "Allows Hermes to create OpenAI Responses and nothing else"
  permissions = local.runtime_permissions
}

resource "openai_group" "hermes" {
  name = local.access_group_name
}

resource "openai_group_user" "hermes" {
  group_id = openai_group.hermes.group_id
  user_id  = openai_project_service_account.hermes.id
}

resource "openai_project_group_role" "hermes" {
  project_id = openai_project.hermes.project_id
  group_id   = openai_group.hermes.group_id
  role_id    = openai_project_role.hermes.role_id
}

resource "openai_project_model_permissions" "hermes" {
  project_id = openai_project.hermes.project_id
  mode       = "allow_list"
  model_ids  = ["gpt-5.6-luna"]
}

resource "openai_project_hosted_tool_permissions" "hermes" {
  project_id               = openai_project.hermes.project_id
  file_search_enabled      = false
  web_search_enabled       = false
  image_generation_enabled = false
  mcp_enabled              = false
  code_interpreter_enabled = false
}

resource "openai_project_spend_limit" "hermes" {
  project_id       = openai_project.hermes.project_id
  threshold_amount = 5000
  currency         = "USD"
  interval         = "month"
}

output "project_id" {
  value = openai_project.hermes.project_id
}

output "service_account_id" {
  value = openai_project_service_account.hermes.service_account_id
}

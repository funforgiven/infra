terraform {
  required_version = ">= 1.12.1, < 1.13.0"
  required_providers {
    openstack = {
      source  = "terraform-provider-openstack/openstack"
      version = "= 3.4.0"
    }
  }
}

provider "openstack" {
  tenant_id           = ""
  tenant_name         = "gitlab"
  project_domain_name = "Default"
}

variable "image_revision" {
  type        = string
  description = "Full signed revision of promoted NixOS GitLab/runner images"
  validation {
    condition     = can(regex("^[0-9a-f]{40}$", var.image_revision))
    error_message = "Promote a signed full Git revision before provisioning."
  }
}

# Retirement transition: the replacement and the retained native GitLab
# recovery bundle are qualified independently. This empty root preserves the
# original Terraform backend while producing a reviewable deletion plan for
# only the old GitLab data VM, its disk, address and security group.
# Remove this transition root after the state has no managed resources.

variable "source_revision" {
  description = "Signed Git revision containing the NixOS mail appliance configuration"
  type        = string

  validation {
    condition = (
      can(regex("^[0-9a-f]{40}$", var.source_revision)) &&
      var.source_revision != "0000000000000000000000000000000000000000"
    )
    error_message = "source_revision must be a non-sentinel, full lowercase Git commit."
  }
}

variable "enable_reverse_dns" {
  description = "Create the EIP PTR only after forward DNS has propagated to the AWS address"
  type        = bool
  default     = false
}

locals {
  service_name = "stalwart-mail"
  tags = {
    Environment = "production"
    ManagedBy   = "opentofu"
    Service     = local.service_name
  }
}

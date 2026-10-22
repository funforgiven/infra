variable "enable_reverse_dns" {
  description = "Create the EIP PTR only after forward DNS has propagated to the AWS address"
  type        = bool
}

variable "enable_restore_qualification" {
  description = "Create an isolated disposable PostgreSQL target for a controlled logical restore drill"
  type        = bool
  default     = false
}

locals {
  # Signed commit a newly created instance builds on first boot. Bump it to a
  # recent signed main commit before recreating the instance.
  bootstrap_revision = "7078aefa3cc4301454cb4f443a1b15cdf2d66778"
  service_name       = "stalwart-mail"
  tags = {
    Environment = "production"
    ManagedBy   = "opentofu"
    Service     = local.service_name
  }
}

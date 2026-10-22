# Operator-held credentials are canonical in SOPS. They are read as ephemeral
# values and sent as write-only attributes, so they never enter state or plans.
# A changed SOPS file (new ciphertext) publishes a new secret version.
locals {
  repository = "${path.module}/../../../.."
  sops_files = {
    resend     = "${local.repository}/deployments/homelab/credentials/mail-aws/resend.sops.yaml"
    backups    = "${local.repository}/deployments/homelab/credentials/host-runtime/backups.sops.yaml"
    generated  = "${local.repository}/deployments/homelab/credentials/host-runtime/generated.sops.yaml"
    vpn        = "${local.repository}/secrets/mail-vpn.yaml"
    cloudflare = "${local.repository}/deployments/homelab/credentials/cloudflare-token.sops.yaml"
  }
  secret_sources = {
    resend = [local.sops_files.resend]
    backup = [local.sops_files.backups, local.sops_files.generated]
    vpn    = [local.sops_files.vpn, local.sops_files.cloudflare]
  }
  secret_versions = {
    for name, files in local.secret_sources :
    name => parseint(substr(sha256(join("", [for file in files : filesha256(file)])), 0, 8), 16)
  }
}

ephemeral "sops_file" "credentials" {
  for_each    = local.sops_files
  source_file = each.value
}

resource "aws_secretsmanager_secret_version" "resend" {
  secret_id                = aws_secretsmanager_secret.resend.id
  secret_string_wo         = base64decode(ephemeral.sops_file.credentials["resend"].data["data.STALWART_RESEND_API_KEY"])
  secret_string_wo_version = local.secret_versions.resend
}

resource "aws_secretsmanager_secret_version" "backup" {
  secret_id = aws_secretsmanager_secret.backup.id
  secret_string_wo = jsonencode({
    MAIL_AWS_BACKUP_B2_APPLICATION_KEY_ID = base64decode(ephemeral.sops_file.credentials["backups"].data["data.MAIL_AWS_BACKUP_B2_APPLICATION_KEY_ID"])
    MAIL_AWS_BACKUP_B2_APPLICATION_KEY    = base64decode(ephemeral.sops_file.credentials["backups"].data["data.MAIL_AWS_BACKUP_B2_APPLICATION_KEY"])
    MAIL_AWS_BACKUP_RESTIC_PASSWORD       = base64decode(ephemeral.sops_file.credentials["generated"].data["data.MAIL_AWS_BACKUP_RESTIC_PASSWORD"])
  })
  secret_string_wo_version = local.secret_versions.backup
}

# The homelab client's private key stays in secrets/mail-vpn-client.yaml.
resource "aws_secretsmanager_secret_version" "vpn" {
  secret_id = aws_secretsmanager_secret.vpn.id
  secret_string_wo = jsonencode({
    private_key          = ephemeral.sops_file.credentials["vpn"].data["private_key"]
    preshared_key        = ephemeral.sops_file.credentials["vpn"].data["preshared_key"]
    direct_private_key   = ephemeral.sops_file.credentials["vpn"].data["direct_private_key"]
    direct_preshared_key = ephemeral.sops_file.credentials["vpn"].data["direct_preshared_key"]
    dns_api_token        = ephemeral.sops_file.credentials["cloudflare"].data["stringData.api-token"]
  })
  secret_string_wo_version = local.secret_versions.vpn
}

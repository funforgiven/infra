# shellcheck shell=bash
set -euo pipefail
umask 077

if [[ "$#" -ne 2 ]]; then
  echo 'Usage: enroll-service-host-secrets SSH_TARGET PROFILE' >&2
  echo 'Profiles: monitoring hermes-openai hermes-integrations mail-runtime hermes-backup home-assistant-backup mail-edge-backup' >&2
  exit 64
fi

readonly ssh_target="$1"
readonly profile="$2"
repository_root="$(git rev-parse --show-toplevel)"
readonly repository_root

if [[ "$ssh_target" == -* || ! "$ssh_target" =~ ^[A-Za-z0-9_.@:-]+$ ]]; then
  echo 'SSH_TARGET contains unsupported characters.' >&2
  exit 64
fi

read_sops_value() {
  local variable="$1"
  local key="$2"
  local pattern="$3"
  local minimum="$4"
  local maximum="$5"
  local relative_secret_file
  local value

  relative_secret_file="$(
    runtime-contract \
      --repository-root "$repository_root" \
      managed-key-file "$key"
  )"
  value="$(
    sops decrypt \
      --extract "[\"data\"][\"$key\"]" \
      --output-type binary \
      "$repository_root/$relative_secret_file" | base64 --decode
  )"
  if [[ "${#value}" -lt "$minimum" ]] ||
    [[ "${#value}" -gt "$maximum" ]] ||
    [[ ! "$value" =~ $pattern ]]; then
    unset value
    echo "$key in $relative_secret_file is missing or invalid." >&2
    exit 1
  fi
  printf -v "$variable" '%s' "$value"
  unset value
}

prepare_directory() {
  # The client-side value is selected only from constant paths below.
  # shellcheck disable=SC2029
  ssh "$ssh_target" "sudo install -d -o root -g root -m 0700 '$1'"
}

install_stream() {
  local destination="$1"
  # The destination is a constant allow-listed path; bytes cross only stdin.
  # shellcheck disable=SC2029
  ssh "$ssh_target" \
    "sudo install -o root -g root -m 0400 /dev/stdin '$destination'"
}

enroll_monitoring() {
  local bot_token
  local chat_id
  read_sops_value bot_token INFRA_TELEGRAM_BOT_TOKEN \
    '^[0-9]+:[A-Za-z0-9_-]+$' 32 256
  read_sops_value chat_id INFRA_TELEGRAM_CHAT_ID '^-?[0-9]+$' 1 32
  prepare_directory /var/lib/monitoring-bootstrap
  printf '%s' "$bot_token" | \
    install_stream /var/lib/monitoring-bootstrap/bot-token
  printf '%s' "$chat_id" | \
    install_stream /var/lib/monitoring-bootstrap/chat-id
  unset bot_token chat_id
}

enroll_hermes_openai() {
  local openai_api_key
  read_sops_value openai_api_key OPENAI_API_KEY '^sk-[A-Za-z0-9_-]+$' 20 1024
  prepare_directory /var/lib/hermes-bootstrap
  printf 'OPENAI_API_KEY=%s\n' "$openai_api_key" | \
    install_stream /var/lib/hermes-bootstrap/openai.env
  unset openai_api_key
}

enroll_hermes_integrations() {
  local bot_token
  local allowed_users
  local home_channel
  local karakeep_key
  read_sops_value bot_token HERMES_TELEGRAM_BOT_TOKEN \
    '^[0-9]+:[A-Za-z0-9_-]+$' 32 256
  read_sops_value allowed_users HERMES_TELEGRAM_ALLOWED_USERS \
    '^[0-9]+(,[0-9]+)*$' 1 512
  read_sops_value home_channel HERMES_TELEGRAM_HOME_CHANNEL '^-?[0-9]+$' 1 32
  read_sops_value karakeep_key HERMES_KARAKEEP_API_KEY \
    '^[A-Za-z0-9._-]+$' 32 512
  prepare_directory /var/lib/hermes-bootstrap
  {
    printf 'TELEGRAM_BOT_TOKEN=%s\n' "$bot_token"
    printf 'TELEGRAM_ALLOWED_USERS=%s\n' "$allowed_users"
    printf 'TELEGRAM_HOME_CHANNEL=%s\n' "$home_channel"
    printf 'KARAKEEP_API_KEY=%s\n' "$karakeep_key"
  } | install_stream /var/lib/hermes-bootstrap/integrations.env
  unset bot_token allowed_users home_channel karakeep_key
}

enroll_mail_runtime() {
  local admin_secret
  local resend_key
  read_sops_value admin_secret STALWART_ADMIN_SECRET '^[A-Za-z0-9]+$' 64 64
  read_sops_value resend_key STALWART_RESEND_API_KEY '^re_[A-Za-z0-9_-]+$' 23 512
  prepare_directory /var/lib/stalwart-bootstrap
  printf '%s' "$admin_secret" | \
    install_stream /var/lib/stalwart-bootstrap/admin-secret
  printf '%s' "$resend_key" | \
    install_stream /var/lib/stalwart-bootstrap/resend-api-key
  unset admin_secret resend_key
}

enroll_backup() {
  local prefix="$1"
  local password_key="$2"
  local key_id_key="$3"
  local application_key_key="$4"
  local restic_password
  local application_key_id
  local application_key

  read_sops_value restic_password "$password_key" '^[A-Za-z0-9]+$' 64 64
  read_sops_value application_key_id "$key_id_key" '^[A-Za-z0-9]+$' 12 64
  read_sops_value application_key "$application_key_key" '^[A-Za-z0-9]+$' 20 128
  prepare_directory /var/lib/backup-bootstrap
  printf 's3:https://s3.us-west-004.backblazeb2.com/fahrican-cloud-recovery/%s' \
    "$prefix" | install_stream /var/lib/backup-bootstrap/repository
  printf '%s' "$restic_password" | \
    install_stream /var/lib/backup-bootstrap/password
  {
    printf 'AWS_ACCESS_KEY_ID=%s\n' "$application_key_id"
    printf 'AWS_SECRET_ACCESS_KEY=%s\n' "$application_key"
    printf 'AWS_DEFAULT_REGION=us-west-004\n'
  } | install_stream /var/lib/backup-bootstrap/environment
  unset restic_password application_key_id application_key
}

case "$profile" in
  monitoring)
    enroll_monitoring
    ;;
  hermes-openai)
    enroll_hermes_openai
    ;;
  hermes-integrations)
    enroll_hermes_integrations
    ;;
  mail-runtime)
    enroll_mail_runtime
    ;;
  hermes-backup)
    enroll_backup \
      services/hosts/hermes \
      HERMES_BACKUP_RESTIC_PASSWORD \
      HERMES_BACKUP_B2_APPLICATION_KEY_ID \
      HERMES_BACKUP_B2_APPLICATION_KEY
    ;;
  home-assistant-backup)
    enroll_backup \
      services/hosts/home-assistant \
      HOME_ASSISTANT_BACKUP_RESTIC_PASSWORD \
      HOME_ASSISTANT_BACKUP_B2_APPLICATION_KEY_ID \
      HOME_ASSISTANT_BACKUP_B2_APPLICATION_KEY
    ;;
  mail-edge-backup)
    enroll_backup \
      services/hosts/mail-edge \
      MAIL_EDGE_BACKUP_RESTIC_PASSWORD \
      MAIL_EDGE_BACKUP_B2_APPLICATION_KEY_ID \
      MAIL_EDGE_BACKUP_B2_APPLICATION_KEY
    ;;
  *)
    echo "Unknown host enrollment profile: $profile" >&2
    exit 64
    ;;
esac

printf '%s\n' \
  "Enrolled '$profile' on '$ssh_target' through SSH standard input." \
  'Plaintext existed only in memory and the destination root-only runtime files.'

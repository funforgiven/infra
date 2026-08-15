# shellcheck shell=bash
set -euo pipefail
umask 077

if [[ "$#" -lt 2 || "$#" -gt 3 ]]; then
  echo 'Usage: enroll-service-host-secrets SSH_TARGET PROFILE [R2_ENDPOINT]' >&2
  echo 'Profiles: monitoring hermes-openai hermes-integrations mail-runtime hermes-backup home-assistant-backup mail-edge-backup' >&2
  exit 64
fi

readonly ssh_target="$1"
readonly profile="$2"
bot_token=
chat_id=
allowed_users=
home_channel=
karakeep_key=
openai_api_key=
admin_secret=
resend_key=
restic_password=
access_key_id=
secret_access_key=
if [[ "$ssh_target" == -* || ! "$ssh_target" =~ ^[A-Za-z0-9_.@:-]+$ ]]; then
  echo 'SSH_TARGET contains unsupported characters.' >&2
  exit 64
fi

prompt_value() {
  local variable="$1"
  local label="$2"
  local pattern="$3"
  local minimum="$4"
  local maximum="$5"
  local value
  local confirmation

  printf 'Enter %s (input hidden): ' "$label" >&2
  IFS= read -r -s value
  printf '\nRepeat %s: ' "$label" >&2
  IFS= read -r -s confirmation
  printf '\n' >&2
  if [[ "$value" != "$confirmation" ]] ||
    [[ "${#value}" -lt "$minimum" ]] ||
    [[ "${#value}" -gt "$maximum" ]] ||
    [[ ! "$value" =~ $pattern ]]; then
    unset value confirmation
    echo "$label was empty, mismatched, or invalid." >&2
    exit 1
  fi
  printf -v "$variable" '%s' "$value"
  unset value confirmation
}

read_sops_value() {
  local variable="$1"
  local key="$2"
  local minimum="$3"
  local maximum="$4"
  local repository_root
  local relative_secret_file
  local value

  repository_root="$(git rev-parse --show-toplevel)"
  relative_secret_file="$(runtime-contract --repository-root "$repository_root" key-file "$key")"
  value="$(
    sops decrypt \
      --extract "[\"data\"][\"$key\"]" \
      --output-type binary \
      "$repository_root/$relative_secret_file" | base64 --decode
  )"
  if [[ "${#value}" -lt "$minimum" ]] ||
    [[ "${#value}" -gt "$maximum" ]] ||
    [[ ! "$value" =~ ^[^[:space:]]+$ ]]; then
    unset value
    echo "$key in $relative_secret_file is missing or invalid." >&2
    exit 1
  fi
  printf -v "$variable" '%s' "$value"
  unset value
}

prepare_directory() {
  # The client-side value is selected only from the constant paths below and
  # is intentionally expanded before the SSH boundary.
  # shellcheck disable=SC2029
  ssh "$ssh_target" "sudo install -d -o root -g root -m 0700 '$1'"
}

install_stream() {
  local destination="$1"
  # The destination is a constant allow-listed path; credential bytes travel
  # exclusively through this function's standard input.
  # shellcheck disable=SC2029
  ssh "$ssh_target" \
    "sudo install -o root -g root -m 0400 /dev/stdin '$destination'"
}

case "$profile" in
  monitoring)
    [[ "$#" -eq 2 ]]
    prompt_value bot_token 'infrastructure Telegram bot token' \
      '^[0-9]+:[A-Za-z0-9_-]+$' 32 256
    prompt_value chat_id 'infrastructure Telegram chat ID' \
      '^-?[0-9]+$' 1 32
    prepare_directory /var/lib/monitoring-bootstrap
    printf '%s' "$bot_token" | \
      install_stream /var/lib/monitoring-bootstrap/bot-token
    printf '%s' "$chat_id" | \
      install_stream /var/lib/monitoring-bootstrap/chat-id
    unset bot_token chat_id
    ;;
  hermes-openai)
    [[ "$#" -eq 2 ]]
    read_sops_value openai_api_key OPENAI_API_KEY 20 1024
    prepare_directory /var/lib/hermes-bootstrap
    printf 'OPENAI_API_KEY=%s\n' "$openai_api_key" | \
      install_stream /var/lib/hermes-bootstrap/openai.env
    unset openai_api_key
    ;;
  hermes-integrations)
    [[ "$#" -eq 2 ]]
    prompt_value bot_token 'Hermes Telegram bot token' \
      '^[0-9]+:[A-Za-z0-9_-]+$' 32 256
    prompt_value allowed_users 'comma-separated Telegram user allowlist' \
      '^[0-9]+(,[0-9]+)*$' 1 512
    prompt_value home_channel 'Hermes Telegram home channel ID' \
      '^-?[0-9]+$' 1 32
    prompt_value karakeep_key 'Hermes Karakeep API key' \
      '^[A-Za-z0-9._-]+$' 32 512
    prepare_directory /var/lib/hermes-bootstrap
    {
      printf 'TELEGRAM_BOT_TOKEN=%s\n' "$bot_token"
      printf 'TELEGRAM_ALLOWED_USERS=%s\n' "$allowed_users"
      printf 'TELEGRAM_HOME_CHANNEL=%s\n' "$home_channel"
      printf 'KARAKEEP_API_KEY=%s\n' "$karakeep_key"
    } | install_stream /var/lib/hermes-bootstrap/integrations.env
    unset bot_token allowed_users home_channel karakeep_key
    ;;
  mail-runtime)
    [[ "$#" -eq 2 ]]
    prompt_value admin_secret 'Stalwart fallback administrator secret' \
      '^.+$' 32 1024
    prompt_value resend_key 'Resend domain sending key' \
      '^re_[A-Za-z0-9_-]+$' 23 512
    prepare_directory /var/lib/stalwart-bootstrap
    printf '%s' "$admin_secret" | \
      install_stream /var/lib/stalwart-bootstrap/admin-secret
    printf '%s' "$resend_key" | \
      install_stream /var/lib/stalwart-bootstrap/resend-api-key
    unset admin_secret resend_key
    ;;
  hermes-backup | home-assistant-backup | mail-edge-backup)
    [[ "$#" -eq 3 ]]
    readonly endpoint="$3"
    if [[ ! "$endpoint" =~ ^https://[0-9a-f]{32}\.r2\.cloudflarestorage\.com$ ]]; then
      echo 'R2_ENDPOINT must be the exact OpenTofu account endpoint.' >&2
      exit 64
    fi
    case "$profile" in
      hermes-backup) bucket=fahrican-hermes-backup ;;
      home-assistant-backup) bucket=fahrican-home-assistant-backup ;;
      mail-edge-backup) bucket=fahrican-mail-edge-backup ;;
    esac
    prompt_value restic_password 'Restic repository password' \
      '^.+$' 32 1024
    prompt_value access_key_id 'bucket-scoped R2 access key ID' \
      '^[A-Za-z0-9_-]+$' 16 256
    prompt_value secret_access_key 'bucket-scoped R2 secret access key' \
      '^[A-Za-z0-9/+_-]+={0,2}$' 32 512
    prepare_directory /var/lib/backup-bootstrap
    printf 's3:%s/%s' "$endpoint" "$bucket" | \
      install_stream /var/lib/backup-bootstrap/repository
    printf '%s' "$restic_password" | \
      install_stream /var/lib/backup-bootstrap/password
    {
      printf 'AWS_ACCESS_KEY_ID=%s\n' "$access_key_id"
      printf 'AWS_SECRET_ACCESS_KEY=%s\n' "$secret_access_key"
      printf 'AWS_DEFAULT_REGION=auto\n'
    } | install_stream /var/lib/backup-bootstrap/environment
    unset restic_password access_key_id secret_access_key
    ;;
  *)
    echo "Unknown host enrollment profile: $profile" >&2
    exit 64
    ;;
esac

printf '%s\n' \
  "Enrolled '$profile' on '$ssh_target' through SSH standard input." \
  'No plaintext credential was placed in an argument, local file, or repository.'

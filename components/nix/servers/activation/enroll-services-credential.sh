# shellcheck shell=bash
set -euo pipefail
umask 077

from_file=false
if [[ "${1:-}" == "--from-file" ]]; then
  from_file=true
  shift
fi

if [[ "$#" -ne 1 ]]; then
  echo "Usage: enroll-services-credential [--from-file] KEY" >&2
  exit 64
fi

readonly key="$1"
repository_root="$(git rev-parse --show-toplevel)"
readonly repository_root
cd "$repository_root"
relative_secret_file="$(runtime-contract key-file "$key")"
readonly relative_secret_file
secret_file="$repository_root/$relative_secret_file"
readonly secret_file
[[ -f "$secret_file" ]]
sops filestatus "$secret_file" | rg --quiet '"encrypted":true'

if [[ "$from_file" == true ]]; then
  source_file="$repository_root/secrets/$key.key"
  readonly source_file
  if [[ ! -f "$source_file" || -L "$source_file" ]] ||
    [[ "$(stat --format=%a "$source_file")" != 600 ]]; then
    echo "secrets/$key.key must be a regular, non-symlink mode-0600 file." >&2
    exit 1
  fi
  value="$(<"$source_file")"
else
  printf 'Enter %s (input hidden): ' "$key" >&2
  IFS= read -r -s value
  printf '\nRepeat %s: ' "$key" >&2
  IFS= read -r -s confirmation
  printf '\n' >&2
  if [[ "$value" != "$confirmation" ]]; then
    unset value confirmation
    echo 'Values did not match.' >&2
    exit 1
  fi
  unset confirmation
fi
if [[ -z "$value" || "$value" == *$'\n'* || "$value" == *$'\r'* ]]; then
  unset value
  echo 'Credential must be a non-empty single-line value.' >&2
  exit 1
fi

encoded="$(printf '%s' "$value" | base64 --wrap=0)"
unset value
printf '%s' "$encoded" | jq --raw-input . | \
  sops set --value-stdin "$secret_file" "[\"data\"][\"$key\"]"
unset encoded
if [[ "$from_file" == true ]]; then
  truncate --size=0 "$source_file"
fi

printf '%s\n' \
  "$key was added to $relative_secret_file as SOPS ciphertext." \
  'No plaintext value was printed, written to Git, or passed as an argument.'
if [[ "$from_file" == true ]]; then
  printf '%s\n' "secrets/$key.key was cleared after successful enrollment."
fi

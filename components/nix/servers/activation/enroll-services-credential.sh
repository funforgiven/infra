# shellcheck shell=bash
set -euo pipefail
umask 077

if [[ "$#" -ne 1 ]]; then
  echo "Usage: enroll-services-credential KEY" >&2
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

printf 'Enter %s (input hidden): ' "$key" >&2
IFS= read -r -s value
printf '\nRepeat %s: ' "$key" >&2
IFS= read -r -s confirmation
printf '\n' >&2
if [[ -z "$value" || "$value" != "$confirmation" ]]; then
  unset value confirmation
  echo 'Values were empty or did not match.' >&2
  exit 1
fi

encoded="$(printf '%s' "$value" | base64 --wrap=0)"
unset value confirmation
printf '%s' "$encoded" | jq --raw-input . | \
  sops set --value-stdin "$secret_file" "[\"data\"][\"$key\"]"
unset encoded

printf '%s\n' \
  "$key was added to $relative_secret_file as SOPS ciphertext." \
  'No plaintext value was written to Git or passed as an argument.'

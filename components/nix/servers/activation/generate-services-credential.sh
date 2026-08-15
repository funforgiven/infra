# shellcheck shell=bash
set -euo pipefail
umask 077

rotate=false
if [[ "${1:-}" == "--rotate" ]]; then
  rotate=true
  shift
fi

if [[ "$#" -ne 1 ]]; then
  echo 'Usage: generate-services-credential [--rotate] KEY' >&2
  exit 64
fi

readonly key="$1"
repository_root="$(git rev-parse --show-toplevel)"
readonly repository_root
cd "$repository_root"
relative_secret_file="$(runtime-contract generated-key-file "$key")"
readonly relative_secret_file
secret_file="$repository_root/$relative_secret_file"
readonly secret_file
[[ -f "$secret_file" ]]
sops filestatus "$secret_file" | rg --quiet '"encrypted":true'

if [[ "$rotate" == false ]] &&
  sops decrypt \
    --extract "[\"data\"][\"$key\"]" \
    --output-type binary \
    "$secret_file" >/dev/null 2>&1; then
  echo "$key already exists; pass --rotate to replace it." >&2
  exit 1
fi

value="$(openssl rand -hex 32)"
encoded="$(printf '%s' "$value" | base64 --wrap=0)"
unset value
printf '%s' "$encoded" | jq --raw-input . | \
  sops set --value-stdin "$secret_file" "[\"data\"][\"$key\"]"
unset encoded

printf '%s\n' \
  "$key was generated into $relative_secret_file as SOPS ciphertext." \
  'No plaintext value was printed, persisted separately, or passed as an argument.'

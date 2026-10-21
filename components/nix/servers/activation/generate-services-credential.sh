# shellcheck shell=bash
set -euo pipefail
umask 077

usage() {
  cat <<'EOF'
Usage: generate-services-credential [--rotate] KEY

Generate one repository-owned secret directly into its declared SOPS file.
Use --rotate to replace an existing value.
EOF
}

if [[ "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

rotate=false
if [[ "${1:-}" == "--rotate" ]]; then
  rotate=true
  shift
fi

if [[ "$#" -ne 1 ]]; then
  usage >&2
  exit 64
fi

readonly key="$1"
repository_root="$(git rev-parse --show-toplevel)"
readonly repository_root
cd "$repository_root"
relative_secret_file="$(runtime-contract generated-key-file "$key")"
readonly relative_secret_file
sops filestatus "$repository_root/$relative_secret_file" | rg --quiet '"encrypted":true'

write_options=(--no-replace)
if [[ "$rotate" == true ]]; then
  write_options=()
fi
if ! openssl rand -hex 32 | tr -d '\n' |
  sops-credential --repository-root "$repository_root" \
    write "${write_options[@]}" "$relative_secret_file" "$key"; then
  if [[ "$rotate" == false ]]; then
    echo 'Pass --rotate to replace an existing value.' >&2
  fi
  exit 1
fi

printf '%s\n' \
  "$key was generated into $relative_secret_file as SOPS ciphertext." \
  'No plaintext value was printed, persisted separately, or passed as an argument.'

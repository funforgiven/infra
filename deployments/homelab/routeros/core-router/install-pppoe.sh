#!/usr/bin/env bash

set -euo pipefail

repo_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../../../.." && pwd)

if (( $# > 1 )); then
  printf 'usage: %s [router-host]\n' "$0" >&2
  exit 2
fi

router_host=${1:-192.168.1.1}
readonly router_host

python_arguments=(
  "$repo_root/components/routeros/install_pppoe_credentials.py"
  --host "$router_host"
  --username admin
  --client pppoe-turknet
  --fingerprint SHA256:DRRq3QIbwi2OYjPiMkB+seg6GeE3RXL9kUT8Ws3uI3w
  --pppoe-username-file /run/secrets/homelab-routeros-pppoe-username
  --pppoe-password-file /run/secrets/homelab-routeros-pppoe-password
)

if python3 -c 'import paramiko' >/dev/null 2>&1; then
  exec python3 "${python_arguments[@]}"
fi

exec nix develop "$repo_root" --accept-flake-config \
  -c python3 "${python_arguments[@]}"

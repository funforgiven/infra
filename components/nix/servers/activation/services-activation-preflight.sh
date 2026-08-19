# shellcheck shell=bash
set -euo pipefail

if [[ "$#" -ne 1 ]]; then
  echo 'Usage: services-activation-preflight PHASE' >&2
  echo 'Phases: foundation hosts final' >&2
  exit 64
fi

readonly phase="$1"
deferred_provisioners=()
require_promotions=false
case "$phase" in
  foundation)
    deferred_provisioners=(karakeep-ui reconcile-services-resend)
    ;;
  hosts)
    deferred_provisioners=(karakeep-ui reconcile-services-resend)
    require_promotions=true
    ;;
  final)
    require_promotions=true
    ;;
  *)
    echo "Unknown activation preflight phase: $phase" >&2
    echo 'Phases: foundation hosts final' >&2
    exit 64
    ;;
esac

repository_root="$(git rev-parse --show-toplevel)"
readonly repository_root
cd "$repository_root"
if [[ -n "$(git status --porcelain --untracked-files=normal)" ]]; then
  echo 'Activation requires a clean worktree.' >&2
  exit 1
fi
git verify-commit HEAD >/dev/null

while IFS= read -r secret_file; do
  sops filestatus "$secret_file" | rg --quiet '"encrypted":true'
done < <(runtime-contract secret-files)
verification_arguments=(verify-ciphertext)
for provisioner in "${deferred_provisioners[@]}"; do
  verification_arguments+=(--exclude-provisioner "$provisioner")
done
runtime-contract "${verification_arguments[@]}" >/dev/null

if [[ "$require_promotions" == true ]]; then
  if rg --quiet 'sha256:0{64}' \
    deployments/homelab/cloud/services/40-media \
    deployments/homelab/cloud/versions.yaml; then
    echo 'The media image has not passed signed-revision promotion.' >&2
    exit 1
  fi
  if rg --quiet 'value: "0{40}"' \
    deployments/homelab/cloud/undercloud/83-services-hosts/tofu.yaml; then
    echo 'The service-host images have not passed signed-revision promotion.' >&2
    exit 1
  fi
fi

printf '%s\n' \
  "Repository activation preflight passed for phase '$phase'." \
  'Runtime values will be validated again at their workload boundaries.'

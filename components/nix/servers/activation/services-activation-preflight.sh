# shellcheck shell=bash
set -euo pipefail

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
runtime-contract verify-ciphertext >/dev/null

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

printf '%s\n' \
  'Repository activation preflight passed.' \
  'Runtime values will be validated again at their workload boundaries.'

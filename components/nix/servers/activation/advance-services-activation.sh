# shellcheck shell=bash
set -euo pipefail

if [[ "$#" -ne 1 ]]; then
  echo 'Usage: advance-services-activation STAGE' >&2
  printf 'Stages: %s\n' "$(advance-services-activation-edit --list)" >&2
  exit 64
fi

readonly stage="$1"
repository_root="$(git rev-parse --show-toplevel)"
readonly repository_root
cd "$repository_root"
if [[ -n "$(git status --porcelain --untracked-files=normal)" ]]; then
  echo 'Activation advancement requires a clean worktree.' >&2
  exit 1
fi
git verify-commit HEAD >/dev/null

advance-services-activation-edit "$repository_root" "$stage"
git diff --check
printf '%s\n' \
  "Activation stage '$stage' is now enabled in the declarative manifests." \
  'Review the diff, run the repository checks, create a signed Conventional Commit, and push it directly to main.'

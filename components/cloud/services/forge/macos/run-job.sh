#!/bin/bash
set -eu
umask 077
[ "$(id -un)" = forge-job ]
[ "$(id -u)" -ne 0 ]
if id -Gn | tr ' ' '\n' | grep -qx admin; then
  echo 'Actions must not run with an administrator account' >&2
  exit 1
fi
export PATH=/nix/var/nix/profiles/default/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin
export RUNNER_TOOL_CACHE="$HOME/forge-job/toolcache"
export FORGE_NATIVE_PLATFORM=macos-x86_64
cd "$HOME/forge-job"
cat > runner.yaml <<'YAML'
log:
  level: info
runner:
  capacity: 1
  timeout: 2h
  insecure: false
cache:
  enabled: false
container:
  docker_host: "-"
host:
  workdir_parent: /Users/forge-job/forge-job/work
YAML
trap 'rm -f token' EXIT
/usr/local/bin/forgejo-runner --config runner.yaml one-job \
  --handle "$(cat handle)" --url https://git.fahrican.com \
  --uuid "$(cat uuid)" --token-url "file://$HOME/forge-job/token" \
  --label macos-x86_64:host --label macos:host > runner.log 2>&1

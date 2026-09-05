#!/bin/sh
set -eu
test -s /run/runner/handle || exit 0
nix-store --load-db < /etc/nix/registration
exec forgejo-runner --config /bootstrap/runner.yaml one-job \
  --handle "$(cat /run/runner/handle)" \
  --url https://git.fahrican.com --uuid "$(cat /run/runner/uuid)" \
  --token-url file:/run/runner/token \
  --label linux-x86_64:host --label linux:host

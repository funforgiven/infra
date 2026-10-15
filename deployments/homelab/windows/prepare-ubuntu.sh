#!/usr/bin/env bash
set -euo pipefail

if [[ $(uname -r) != *microsoft-standard-WSL2* ]]; then
  echo 'This bootstrap is for the Gorgonzola Ubuntu WSL2 instance.' >&2
  exit 1
fi

if [[ $(id -u) == 0 ]]; then
  bootstrap_dir=$(cd -- "$(dirname -- "$0")" && pwd)
  apt-get update
  DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    ca-certificates curl git jq openssh-client python3 python3-venv ripgrep \
    nix-bin nix-setup-systemd
  usermod -aG nix-users funforgiven
  install -d -m 0755 /etc/nix/nix.conf.d
  printf '%s\n' 'experimental-features = nix-command flakes' \
    > /etc/nix/nix.conf.d/gorgonzola.conf
  if ! grep -qFx 'include /etc/nix/nix.conf.d/gorgonzola.conf' /etc/nix/nix.conf; then
    printf '\n%s\n' 'include /etc/nix/nix.conf.d/gorgonzola.conf' >> /etc/nix/nix.conf
  fi
  systemctl enable --now nix-daemon.socket
  systemctl restart nix-daemon.service
  install -d -o funforgiven -g funforgiven -m 0755 \
    /home/funforgiven/dev /home/funforgiven/dev/scratch \
    /home/funforgiven/Pictures/Wallpapers
  # This public asset is the existing absolute-path input locked by infra.
  install -o funforgiven -g funforgiven -m 0644 "$bootstrap_dir/wallpaper.png" \
    /home/funforgiven/Pictures/Wallpapers/current.png
  exec runuser -u funforgiven -- bash "$0" --user
fi

[[ $(id -un) == funforgiven && ${1:-} == --user ]]
git config --global user.name funforgiven
git config --global user.email fahricanelidemir@gmail.com
git config --global init.defaultBranch main
git config --global pull.rebase true
git config --global fetch.prune true
git config --global core.autocrlf input
if [[ ! -e /home/funforgiven/dev/infra ]]; then
  git clone https://github.com/funforgiven/infra.git /home/funforgiven/dev/infra
fi
cd /home/funforgiven/dev/infra
[[ $(git remote get-url origin) == https://github.com/funforgiven/infra.git ]]
nix --version
nix store info
[[ $(nix hash path /home/funforgiven/Pictures/Wallpapers/current.png) == \
  'sha256-E9RQGI8XJjhK5MgoRn8y0LsiueROzIoJuLbSJkofCZg=' ]]
nix develop --accept-flake-config --no-write-lock-file --command \
  bash -ec 'git --version; nix --version; sops --version; kubectl version --client; python --version'
git status --short
echo 'Ubuntu infrastructure workspace verified.'

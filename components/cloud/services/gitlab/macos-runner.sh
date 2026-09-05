#!/usr/bin/env bash
# Run inside macOS as the dedicated, logged-in, non-administrator ci user.
set -euo pipefail
umask 077
[[ $(uname -s) == Darwin && $(uname -m) == x86_64 ]]
[[ $(id -u) -ne 0 ]]
if id -Gn | tr ' ' '\n' | grep -qx admin; then
  echo 'Use a dedicated non-administrator CI account.' >&2
  exit 1
fi
[[ $# -eq 1 ]] || { echo 'Usage: macos-runner.sh TOKEN_FILE' >&2; exit 64; }
token_file=$1
[[ $(stat -f '%Lp' "$token_file") == 600 || $(stat -f '%Lp' "$token_file") == 400 ]]
IFS= read -r token < "$token_file"
[[ "$token" =~ ^glrt-[A-Za-z0-9_.-]+$ ]]
install -d -m 0700 "$HOME/bin" "$HOME/.gitlab-runner" "$HOME/ci-builds"
binary="$HOME/bin/gitlab-runner"
curl --fail --location --proto '=https' --tlsv1.2 \
  https://gitlab-runner-downloads.s3.amazonaws.com/v19.3.1/binaries/gitlab-runner-darwin-amd64 \
  --output "$binary.next"
printf '%s  %s\n' 9bed777111a508bfd450e8354fe8980c7c4894dbfaf903808e1c9f102a696c68 "$binary.next" | shasum -a 256 -c -
chmod 0700 "$binary.next"
mv "$binary.next" "$binary"
cat > "$HOME/.gitlab-runner/config.toml" <<EOF
concurrent = 1
check_interval = 3
shutdown_timeout = 1800
[[runners]]
  name = "macos-quickemu"
  url = "https://gitlab.fahrican.com"
  token = "$token"
  executor = "shell"
  shell = "bash"
  limit = 1
  builds_dir = "$HOME/ci-builds"
  output_limit = 16384
EOF
unset token
chmod 0600 "$HOME/.gitlab-runner/config.toml"
"$binary" install --working-directory "$HOME/ci-builds"
"$binary" start
echo 'Runner installed as a per-user LaunchAgent. Qualify Xcode and a protected-branch pipeline.'

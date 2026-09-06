#!/bin/bash
# Run as root in the maintained image after the pinned tools are installed.
set -euo pipefail
umask 077
export PATH=/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin
[ "$(id -u)" -eq 0 ]
[ "$(uname -m)" = x86_64 ]
csrutil status | grep -q 'enabled'
csrutil authenticated-root status | grep -q 'enabled'
if nvram boot-args | grep -Eq 'amfi_get_out_of_my_way|cs_enforcement_disable'; then exit 1; fi
source_dir="$(cd "$(dirname "$0")" && pwd)"
if ! id forge-job >/dev/null 2>&1; then
  # The random local password is discarded. SSH is removed when sealing;
  # only the fixed root launch daemon starts this non-administrator account.
  if dscl . -search /Users UniqueID 502 | grep -q .; then
    echo 'UID 502 is already assigned' >&2
    exit 1
  fi
  dscl . -create /Users/forge-job
  dscl . -create /Users/forge-job UniqueID 502
  dscl . -create /Users/forge-job PrimaryGroupID 20
  dscl . -create /Users/forge-job UserShell /bin/bash
  dscl . -create /Users/forge-job NFSHomeDirectory /Users/forge-job
  dscl . -create /Users/forge-job RealName 'Forgejo disposable job'
  dscl . -create /Users/forge-job IsHidden 1
  dscl . -passwd /Users/forge-job "$(openssl rand -hex 32)"
fi
if id -Gn forge-job | tr ' ' '\n' | grep -qx admin; then exit 1; fi
install -d -o forge-job -g staff -m 0700 /Users/forge-job
# install -d honors the restrictive umask for intermediate directories.
# The job account must traverse libexec while only root can modify it.
install -d -o root -g wheel -m 0755 /usr/local/libexec /usr/local/libexec/forge
for name in start-job.sh run-job.sh enroll-job.js mount-job.js; do
  install -o root -g wheel -m 0755 "$source_dir/$name" "/usr/local/libexec/forge/$name"
done
install -o root -g wheel -m 0644 "$source_dir/com.fahrican.forge-job.plist" /Library/LaunchDaemons/com.fahrican.forge-job.plist
plutil -lint /Library/LaunchDaemons/com.fahrican.forge-job.plist
su -l forge-job -c 'set -e; test -x /usr/local/libexec/forge/run-job.sh; id; /usr/local/bin/node --version; /usr/local/bin/forgejo-runner --version; /nix/var/nix/profiles/default/bin/nix store info'
echo 'Native job account and immutable launch daemon installed.'

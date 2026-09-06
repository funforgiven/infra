#!/bin/bash
# Final image cleanup from signed macOS Recovery. The last secure-token
# administrator cannot be deleted through a running system's account API.
set -euo pipefail
umask 077
export PATH=/usr/bin:/bin:/usr/sbin:/sbin
[ "$(id -u)" -eq 0 ]
target='/Volumes/ForgeMac - Data'
node="$target/private/var/db/dslocal/nodes/Default"
builder="$node/users/forge-builder.plist"
plist=/usr/libexec/PlistBuddy
[ -f "$target/Library/LaunchDaemons/com.fahrican.forge-job.plist" ]
[ -f "$target/usr/local/libexec/forge/seal-image.sh" ]
[ "$($plist -c 'Print :name:0' "$builder")" = forge-builder ]
[ "$($plist -c 'Print :uid:0' "$builder")" = 501 ]
[ "$($plist -c 'Print :uid:0' "$node/users/forge-job.plist")" = 502 ]
builder_guid="$($plist -c 'Print :generateduid:0' "$builder")"
[ -n "$builder_guid" ]
# This targets only the offline builder's name and UUID; preserve all other
# group entries, including Nix build users and the unprivileged job account.
for group in "$node"/groups/*.plist; do
  for attribute in users groupmembers; do
    index=0
    while value="$($plist -c "Print :$attribute:$index" "$group" 2>/dev/null)"; do
      if [ "$value" = forge-builder ] || [ "$value" = "$builder_guid" ]; then
        "$plist" -c "Delete :$attribute:$index" "$group"
      else
        index=$((index + 1))
      fi
    done
  done
done
rm "$builder"
rm -rf "$target/Users/forge-builder" "$target/Users/forge-job"
mkdir -m 0700 "$target/Users/forge-job"
chown 502:20 "$target/Users/forge-job"
rm -f "$target/private/etc/ssh/sshd_config.d/000-forge-builder.conf" "$target"/private/etc/ssh/ssh_host_*
sed -i '' 's/^allowed-users =.*/allowed-users = root forge-job/' "$target/private/etc/nix/nix.conf"
rm -rf "$target/private/var/root/.ssh"
rm -f "$target/private/etc/kcpassword" "$target/Library/LaunchDaemons/com.fahrican.forge-seal.plist"
"$plist" -c 'Delete :autoLoginUser' "$target/Library/Preferences/com.apple.loginwindow.plist" 2>/dev/null || true
disabled="$target/private/var/db/com.apple.xpc.launchd/disabled.plist"
"$plist" -c 'Delete :com.openssh.sshd' "$disabled" 2>/dev/null || true
"$plist" -c 'Add :com.openssh.sshd bool true' "$disabled"
# SSH is disabled persistently; a sealed image has no interactive administrator.
[ "$($plist -c 'Print :com.openssh.sshd' "$disabled")" = true ]
[ ! -e "$builder" ]
[ ! -e "$target/Users/forge-builder" ]
[ ! -e "$target/Users/forge-job/forge-job" ]
date -u '+%Y-%m-%dT%H:%M:%SZ' > "$target/private/var/db/forge-image-sealed"
echo 'Forgejo image sealed in Recovery; temporary administrator and remote access removed.'
sync

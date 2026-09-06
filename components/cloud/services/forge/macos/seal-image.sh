#!/bin/bash
# Schedule from the temporary administrator session. A root launch daemon owns
# cleanup so removing that session cannot interrupt the image seal.
set -euo pipefail
umask 077
export PATH=/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin
[ "$(id -u)" -eq 0 ]
if [ "${1:-}" = --schedule ]; then
  [ "$(id -u forge-builder)" -eq 501 ]
  [ "$(id -u forge-job)" -eq 502 ]
  csrutil status | grep -q enabled
  csrutil authenticated-root status | grep -q enabled
  /usr/local/bin/forgejo-runner --version
  /usr/bin/xcrun --find clang
  su -l forge-job -c 'test -x /usr/local/libexec/forge/run-job.sh'
  plutil -lint /Library/LaunchDaemons/com.fahrican.forge-job.plist
  install -o root -g wheel -m 0700 "$0" /usr/local/libexec/forge/seal-image.sh
  cat > /Library/LaunchDaemons/com.fahrican.forge-seal.plist <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.fahrican.forge-seal</string>
  <key>ProgramArguments</key><array><string>/bin/bash</string><string>/usr/local/libexec/forge/seal-image.sh</string><string>--execute</string></array>
  <key>RunAtLoad</key><true/>
  <key>UserName</key><string>root</string>
  <key>StandardOutPath</key><string>/var/log/forge-seal.log</string>
  <key>StandardErrorPath</key><string>/var/log/forge-seal.log</string>
</dict></plist>
PLIST
  chmod 0644 /Library/LaunchDaemons/com.fahrican.forge-seal.plist
  launchctl bootstrap system /Library/LaunchDaemons/com.fahrican.forge-seal.plist
  echo 'Root-owned image seal scheduled; the builder session will end.'
  exit 0
fi
[ "${1:-}" = --execute ]
sleep 10
pwpolicy -u forge-builder -disableuser
launchctl disable system/com.openssh.sshd
launchctl bootout system/com.openssh.sshd || true
pkill -KILL -u 501 || true
sleep 3
# The last secure-token administrator is removed offline by seal-recovery.sh.
# Never mark this preparation phase as a completed image seal.
rm -rf /nix/var/nix/profiles/per-user/forge-builder /nix/var/nix/gcroots/per-user/forge-builder
softwareupdate --schedule off
rm -f /Library/LaunchDaemons/com.fahrican.forge-seal.plist
launchctl print-disabled system | grep -Eq '"com.openssh.sshd" => (disabled|true)'
date -u '+%Y-%m-%dT%H:%M:%SZ' > /var/db/forge-image-awaiting-recovery
echo 'Remote access disabled. Complete seal-recovery.sh from signed Recovery.'
sync
/sbin/shutdown -h now

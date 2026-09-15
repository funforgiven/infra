#!/bin/bash
set -euo pipefail
umask 077
mkdir -p /backups
exec 9>/tmp/thread-backup.lock
flock -n 9
stage="$(mktemp -d /backups/.thread-backup.XXXXXX)"
touch /tmp/backup-active
resume() {
  s6-svc -u /run/service/otbr-agent
  rm -f /tmp/backup-active
}
cleanup() {
  resume
  rm -rf "$stage"
}
trap cleanup EXIT
trap 'exit 1' INT TERM

# Keep the native dataset private. Publish one complete recovery bundle only
# after all checks pass, preserving the previous bundle on any failure.
ot-ctl dataset active -x | tr -d '\r' | head -n 1 > "$stage/dataset.txt"
grep -Eq '^[[:xdigit:]]{20,510}$' "$stage/dataset.txt"
s6-svc -d /run/service/otbr-agent
s6-svwait -D -t 90000 /run/service/otbr-agent
tar -czf "$stage/thread.tar.gz" -C /data thread
resume
tar -tzf "$stage/thread.tar.gz" >/dev/null
cd "$stage"
date +%s > created-at
sha256sum thread.tar.gz dataset.txt created-at > SHA256SUMS
sha256sum --status -c SHA256SUMS
tar -czf recovery.tar.gz thread.tar.gz dataset.txt created-at SHA256SUMS
tar -tzf recovery.tar.gz >/dev/null
# The restricted metrics/verifier containers read with GID 1000.
chgrp 1000 recovery.tar.gz
chmod 0640 recovery.tar.gz
mv -f recovery.tar.gz /backups/thread-recovery.tar.gz
printf '%s\n' 'Thread recovery archive completed; border router resumed.'

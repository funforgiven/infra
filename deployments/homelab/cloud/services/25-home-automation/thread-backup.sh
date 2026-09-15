#!/bin/bash
set -euo pipefail
umask 077
mkdir -p /backups
touch /tmp/backup-active
resume() {
  s6-svc -u /run/service/otbr-agent
  rm -f /tmp/backup-active
}
trap resume EXIT
trap 'exit 1' INT TERM

# Export the native dataset as well as the stopped border-router state. Neither
# the dataset nor its network key is printed in logs.
ot-ctl dataset active -x | head -n 1 > /backups/dataset.partial.txt
grep -Eq '^[[:xdigit:]]{20,510}$' /backups/dataset.partial.txt
s6-svc -d /run/service/otbr-agent
s6-svwait -d -t 90000 /run/service/otbr-agent
tar -czf /backups/thread.partial.tar.gz -C /data thread
tar -tzf /backups/thread.partial.tar.gz >/dev/null
mv -f /backups/thread.partial.tar.gz /backups/thread.tar.gz
mv -f /backups/dataset.partial.txt /backups/dataset.txt
cd /backups
sha256sum thread.tar.gz dataset.txt > SHA256SUMS
date +%s > last-success

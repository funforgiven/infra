#!/usr/bin/env bash
set -euo pipefail
umask 077
readonly bootstrap=/var/lib/backup-bootstrap
readonly staging=/var/lib/unifi-backup
readonly metrics=/var/lib/prometheus/node-exporter
for file in repository password environment; do
  test -s "$bootstrap/$file"
done
install -d -m 0700 "$staging"
exec 9>/run/lock/unifi-backup.lock
flock -n 9
export RESTIC_REPOSITORY_FILE="$bootstrap/repository"
export RESTIC_PASSWORD_FILE="$bootstrap/password"
set -a
# This root-owned file is delivered by enroll-service-host-secrets.
# shellcheck disable=SC1091
source "$bootstrap/environment"
set +a
# Check the repository before interrupting controller management.
restic cat config >/dev/null
systemctl is-active --quiet uosserver
resume() {
  systemctl start uosserver uosserver-updater
}
trap resume EXIT
systemctl stop uosserver-updater uosserver
# The rootless Podman container must be stopped before copying its databases.
uid=$(id -u uosserver)
running=$(runuser -u uosserver -- env XDG_RUNTIME_DIR="/run/user/$uid" \
  podman inspect --format '{{.State.Running}}' uosserver)
test "$running" = false
tar --numeric-owner --acls --xattrs --sparse -cpf "$staging/controller.tar.new" \
  -C / home/uosserver var/lib/uosserver var/lib/unifi-proxy \
  etc/subuid etc/subgid etc/passwd etc/group \
  usr/local/lib/unifi etc/nginx/sites-available/unifi \
  etc/systemd/system/uosserver.service etc/systemd/system/uosserver-updater.service
mv "$staging/controller.tar.new" "$staging/controller.tar"
resume
trap - EXIT
restic backup --host unifi --tag unifi "$staging/controller.tar"
# Retention failure must also surface as a failed backup unit.
restic forget --host unifi --tag unifi --group-by host,tags \
  --keep-daily 14 --keep-weekly 8 --keep-monthly 12 --keep-yearly 3 --prune
install -d -m 0755 "$metrics"
printf 'unifi_backup_last_success_timestamp_seconds %s\n' "$(date +%s)" > "$metrics/unifi-backup.prom.new"
chmod 0644 "$metrics/unifi-backup.prom.new"
mv "$metrics/unifi-backup.prom.new" "$metrics/unifi-backup.prom"

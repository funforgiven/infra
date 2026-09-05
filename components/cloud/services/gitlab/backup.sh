#!/usr/bin/env bash
# Native Helm toolbox archive + Rails/Kubernetes secrets -> encrypted B2 Restic.
set -euo pipefail
umask 077
exec 9>/run/lock/gitlab-maintenance.lock
flock -n 9
export RCLONE_CONFIG=/var/lib/gitlab-bootstrap/rclone.conf
test -s "$RCLONE_CONFIG"
backup_root=/var/lib/gitlab-backup
stage="$backup_root/.next"
install -d -m 0700 "$backup_root"
rm -rf "$stage"
install -d -m 0700 "$stage"
rclone lsjson ceph:gitlab-backups --files-only > "$stage/objects.json"
marker=$(jq -er '[.[] | select(.Name | test("^[0-9]{10}_[0-9]{4}_[0-9]{2}_[0-9]{2}_19\\.3\\.1-ee_complete$"))]
  | sort_by(.ModTime) | last | .Name // error("No complete native backup")' "$stage/objects.json")
id=${marker%_complete}
[[ "$id" =~ ^[0-9]{10}_[0-9]{4}_[0-9]{2}_[0-9]{2}_19\.3\.1-ee$ ]]
now=$(date +%s)
captured=${id%%_*}
test "$captured" -le "$now"
test "$((now - captured))" -lt 93600
rclone copyto "ceph:gitlab-backups/$marker" "$stage/complete"
grep -Fx "$id" "$stage/complete" >/dev/null
archive="${id}_gitlab_backup.tar"
rclone copyto "ceph:gitlab-backups/$archive" "$stage/$archive"
rclone copyto "ceph:gitlab-backups/${id}_secrets.json" "$stage/secrets.json"
jq -e '.items | any(.metadata.name == "gitlab-rails-secret")' "$stage/secrets.json" >/dev/null
cp -a /var/lib/gitlab/config "$stage/backend-config"
cp -a /var/lib/gitlab-bootstrap "$stage/bootstrap"
docker inspect --format '{{.Config.Image}}' gitlab > "$stage/backend-image.txt"
printf '%s\n' 'chart=10.3.1' 'gitlab=19.3.1-ee' 'cluster=gitlab-v1' > "$stage/versions.txt"
(cd "$stage" && sha256sum ./*_gitlab_backup.tar secrets.json > SHA256SUMS)
rm -rf "$backup_root/previous"
if [[ -d "$backup_root/current" ]]; then
  mv "$backup_root/current" "$backup_root/previous"
fi
mv "$stage" "$backup_root/current"

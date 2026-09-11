#!/bin/bash
set -euo pipefail
umask 027

[[ "$POD_NAMESPACE" == games ]]
data="${VALHEIM_DATA_DIR:-/data}"
lock="${VALHEIM_BACKUP_LOCK:-/tmp/valheim-backup.lock}"
mkdir "$lock"
ctl=(supervisorctl -c /bootstrap/supervisord.conf)
cleanup() {
  local result=$?
  trap - EXIT
  # Even a failed copy must resume the game, while failing the Velero hook.
  "${ctl[@]}" start valheim || result=1
  rm -f "$data/backups/recovery.tar.tmp" "$data/backups/recovery.sha256.tmp"
  rmdir "$lock"
  exit "$result"
}
trap cleanup EXIT
trap 'exit 143' TERM
trap 'exit 130' INT

# Valheim has no vanilla RCON save API. SIGINT saves and exits; Supervisor
# remains alive while the stopped world's complete directory tree is archived.
"${ctl[@]}" stop valheim
test -d "$data/worlds/worlds_local/$WORLD_NAME"
find "$data/worlds/worlds_local/$WORLD_NAME" -maxdepth 1 -name '_main.*.ok' \
  -type f -print -quit | grep . >/dev/null
tar -cf "$data/backups/recovery.tar.tmp" -C "$data/worlds" .
tar -tf "$data/backups/recovery.tar.tmp" >/dev/null
mv "$data/backups/recovery.tar.tmp" "$data/backups/recovery.tar"
cd "$data/backups"
sha256sum recovery.tar > recovery.sha256.tmp
mv recovery.sha256.tmp recovery.sha256
# Velero copies the volume after this hook returns. The archive is immutable
# until the next backup, even though live world files resume changing.

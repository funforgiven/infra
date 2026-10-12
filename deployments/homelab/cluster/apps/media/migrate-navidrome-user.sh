#!/bin/sh
set -eu

database=/data/navidrome.db
old_user=fahrican
new_user=funforgiven

if [ ! -s "$database" ]; then
  printf '%s\n' "Navidrome database does not exist yet; no user migration needed"
  exit 0
fi

old_count="$(sqlite3 "$database" "SELECT count(*) FROM user WHERE user_name='$old_user';")"
new_count="$(sqlite3 "$database" "SELECT count(*) FROM user WHERE user_name='$new_user';")"

if [ "$old_count" -eq 1 ] && [ "$new_count" -eq 0 ]; then
  sqlite3 "$database" <<SQL
BEGIN IMMEDIATE;
UPDATE user
SET user_name = '$new_user', updated_at = datetime('now')
WHERE user_name = '$old_user';
COMMIT;
SQL
  printf 'Renamed Navidrome user %s to %s without changing its ID\n' \
    "$old_user" "$new_user"
elif [ "$old_count" -eq 0 ] && [ "$new_count" -eq 1 ]; then
  printf 'Navidrome user %s is already migrated\n' "$new_user"
elif [ "$old_count" -eq 0 ] && [ "$new_count" -eq 0 ]; then
  printf '%s\n' "Neither migration username exists; leaving a fresh database unchanged"
else
  printf '%s\n' "Refusing ambiguous Navidrome username migration" >&2
  exit 1
fi

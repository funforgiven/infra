#!/bin/sh
set -eu

database=/var/www/html/db/wallos.db
backup_directory=/var/www/html/db/backups
partial=

cleanup_partial() {
  if test -n "$partial"; then
    rm -f "$partial"
  fi
}

trap cleanup_partial EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

database_ready() {
  test -s "$database" &&
    test "$(sqlite3 -cmd '.timeout 5000' "$database" \
      "SELECT COUNT(*) FROM migrations WHERE migration = 'migrations/000055.php';")" = 1 &&
    test "$(sqlite3 -cmd '.timeout 5000' "$database" \
      "SELECT COUNT(*) FROM sqlite_master WHERE type = 'index' AND name IN ('idx_subscriptions_user_inactive_next_payment','idx_subscriptions_user_notify_inactive');")" = 2 &&
    test "$(sqlite3 -cmd '.timeout 5000' "$database" \
      "SELECT COUNT(*) FROM pragma_table_info('oauth_settings') WHERE name = 'require_email_verified';")" = 1
}

backup_once() {
  if ! database_ready; then
    echo "Wallos database schema is not ready" >&2
    return 1
  fi

  umask 0077
  mkdir -p "$backup_directory"
  # Keep the temporary name ending in .db for upstream nginx's file deny rule;
  # the Gateway also denies the entire /db path.
  partial="$backup_directory/wallos.partial.$$.db"
  destination="$backup_directory/wallos.db"

  rm -f "$partial"
  if ! sqlite3 -cmd '.timeout 30000' "$database" ".backup '$partial'"; then
    rm -f "$partial"
    partial=
    return 1
  fi
  if test "$(sqlite3 "$partial" 'PRAGMA integrity_check;')" != ok; then
    echo "Wallos native backup failed its SQLite integrity check" >&2
    rm -f "$partial"
    partial=
    return 1
  fi

  mv -f "$partial" "$destination"
  partial=
  echo "Wallos native backup completed"
}

if test "${1:-}" = --once; then
  backup_once
  exit
fi

while ! backup_once; do
  sleep 30
done

while :; do
  sleep 21600 &
  wait "$!"
  backup_once
done

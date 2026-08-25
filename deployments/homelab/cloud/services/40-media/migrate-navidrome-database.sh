#!/bin/sh
set -eu

database=/data/navidrome.db
pre_migration_backup=/data/backups/pre-0.63.2-migration.db
install -m 0555 /app/navidrome /bootstrap-bin/navidrome
if [ -s "$database" ] && [ ! -e "$pre_migration_backup" ]; then
  mkdir -p /data/backups
  sqlite3 "$database" ".backup '$pre_migration_backup'"
  printf 'Created %s before schema migration\n' "$pre_migration_backup"
fi

/app/navidrome &
navidrome_pid=$!

stop_navidrome() {
  if kill -0 "$navidrome_pid" 2>/dev/null; then
    kill -TERM "$navidrome_pid"
    status=0
    wait "$navidrome_pid" || status=$?
    # A shell may report SIGTERM as 143 even when Navidrome shut down cleanly.
    if [ "$status" -ne 0 ] && [ "$status" -ne 143 ]; then
      return "$status"
    fi
  fi
}
trap stop_navidrome EXIT INT TERM

for attempt in $(seq 1 60); do
  if wget -q -O /dev/null http://127.0.0.1:4533/ping; then
    printf '%s\n' "Navidrome database migrations completed"
    exit 0
  fi
  if ! kill -0 "$navidrome_pid" 2>/dev/null; then
    wait "$navidrome_pid"
    exit 1
  fi
  test "$attempt" -lt 60
  sleep 1
done

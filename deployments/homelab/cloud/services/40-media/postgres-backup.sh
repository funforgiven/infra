#!/bin/sh
set -eu
umask 077

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
temporary="/backups/audiomuse-$timestamp.dump.partial"
destination="/backups/audiomuse-$timestamp.dump"

pg_dump \
  --host "$POSTGRES_HOST" \
  --username "$POSTGRES_USER" \
  --dbname "$POSTGRES_DB" \
  --format custom \
  --file "$temporary"
mv "$temporary" "$destination"
find /backups -maxdepth 1 -type f -name 'audiomuse-*.dump' -print \
  | sort -r \
  | awk 'NR > 3' \
  | while IFS= read -r expired; do
      rm -f -- "$expired"
    done
printf 'Wrote %s\n' "$destination"

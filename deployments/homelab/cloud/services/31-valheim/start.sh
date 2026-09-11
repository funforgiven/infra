#!/bin/bash
set -euo pipefail

if [[ "$POD_NAMESPACE" != games ]]; then
  /bootstrap/verify-backup.sh
  touch /tmp/restore-ready
  echo 'Restore archive verified; the Valheim server will not start in this namespace.'
  exec /bin/sleep infinity
fi

exec /usr/local/bin/supervisord -n -c /bootstrap/supervisord.conf

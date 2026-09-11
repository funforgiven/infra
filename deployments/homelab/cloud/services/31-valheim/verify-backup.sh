#!/bin/bash
set -euo pipefail

cd "${VALHEIM_DATA_DIR:-/data}/backups"
sha256sum --check recovery.sha256
tar -tf recovery.tar >/dev/null
# 1.0 worlds are directory trees, not the pre-1.0 .db/.fwl file pair.
tar -tf recovery.tar | grep -F "./worlds_local/$WORLD_NAME/_main." \
  | grep -E '\.ok$' >/dev/null

#!/bin/bash
set -euo pipefail

if [[ "$POD_NAMESPACE" != games ]]; then
  printf 'Restore isolation is active in namespace %s; the game server will not start.\n' \
    "$POD_NAMESPACE"
  exec /bin/sleep infinity
fi

mkdir -p \
  /factorio/config \
  /factorio/mods \
  /factorio/saves \
  /factorio/scenarios \
  /factorio/script-output

shopt -s nullglob
saves=(/factorio/saves/*.zip)
if (( ${#saves[@]} == 0 )); then
  /opt/factorio/bin/x64/factorio \
    --config=/engine-config/config.ini \
    --create=/factorio/saves/factory.zip \
    --map-gen-settings=/runtime-config/map-gen-settings.json \
    --map-settings=/runtime-config/map-settings.json \
    --mod-directory=/factorio/mods
fi

rcon_password="$(< /runtime-config/rconpw)"
exec /opt/factorio/bin/x64/factorio \
  --config=/engine-config/config.ini \
  --bind=0.0.0.0 \
  --port=34197 \
  --start-server-load-latest \
  --server-settings=/runtime-config/server-settings.json \
  --server-banlist=/runtime-config/server-banlist.json \
  --server-adminlist=/runtime-config/server-adminlist.json \
  --server-id=/factorio/config/server-id.json \
  --mod-directory=/factorio/mods \
  --rcon-bind=127.0.0.1:27015 \
  --rcon-password="$rcon_password"

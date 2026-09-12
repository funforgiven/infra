#!/bin/bash
set -euo pipefail
umask 027

[[ "$POD_NAMESPACE" == games ]]
password="$(< /credentials/VALHEIM_GAME_PASSWORD)"
if (( ${#password} < 12 || ${#password} > 128 )) ||
  [[ "$password" == *$'\n'* || "$password" == *$'\r'* || "$SERVER_NAME" == *"$password"* ]]; then
  echo 'The Valheim password must be 12–128 characters and absent from the server name.' >&2
  exit 1
fi
cd /data/server
/bootstrap/prepare-app480.py
export SteamAppId=480
printf '%s\n' "$SteamAppId" > steam_appid.txt
export LD_LIBRARY_PATH=/data/server/linux64
exec ./valheim_server.x86_64 \
  -nographics -batchmode \
  -name "$SERVER_NAME" -world "$WORLD_NAME" \
  -password "$password" -port 2456 -public 1 \
  -savedir /data/worlds \
  -saveinterval 600 -backups 12 -backupshort 7200 -backuplong 43200

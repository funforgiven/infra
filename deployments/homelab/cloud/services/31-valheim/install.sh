#!/bin/bash
set -euo pipefail
umask 027

# Restore qualification must neither download nor start a second game server.
if [[ "$POD_NAMESPACE" != games ]]; then
  exit 0
fi

mkdir -p /data/worlds /data/backups /data/home/.steam/sdk64 /data/steamcmd /data/server
touch /data/worlds/adminlist.txt /data/worlds/bannedlist.txt /data/worlds/permittedlist.txt
# SteamCMD updates itself, so copy it out of the read-only container filesystem.
if [[ ! -x /data/steamcmd/steamcmd.sh ]]; then
  cp -R /opt/steamcmd/. /data/steamcmd/
  chmod -R u+rwX /data/steamcmd
fi
/data/steamcmd/steamcmd.sh \
  +force_install_dir /data/server \
  +login anonymous \
  +app_update 896660 -beta public validate \
  +quit
test -x /data/server/valheim_server.x86_64
ln -sfn /data/server/linux64/steamclient.so /data/home/.steam/sdk64/steamclient.so

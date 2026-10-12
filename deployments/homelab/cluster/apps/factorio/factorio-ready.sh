#!/bin/sh
set -eu

if [ "$POD_NAMESPACE" != games ]; then
  exit 0
fi

exec /bin/rcon /silent-command 'rcon.print("ready")'

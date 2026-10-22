#!/bin/sh
set -eu

readonly save_name="${1:-}"
case "$save_name" in
  '' | *[!a-z0-9-]*)
    echo 'A lowercase alphanumeric save name is required.' >&2
    exit 64
    ;;
esac

exec /bin/rcon "/server-save $save_name"

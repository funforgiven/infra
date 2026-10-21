#!/bin/sh
set -eu

newline='
'
# Saves already tested, one "path mtime size" entry per line. The watcher keeps
# this in memory and only re-tests saves whose modification time or size changed.
verified="$newline"

verify_once() {
  found=false
  valid=true
  current="$newline"
  for save in /factorio/saves/*.zip; do
    if [ ! -f "$save" ]; then
      continue
    fi
    found=true
    entry="$save $(stat -c '%Y %s' "$save")"
    case "$verified" in
    *"$newline$entry$newline"*) ;;
    *)
      if ! unzip -t "$save" >/dev/null; then
        valid=false
        continue
      fi
      ;;
    esac
    current="$current$entry$newline"
  done
  verified="$current"
  [ "$found" = true ] && [ "$valid" = true ]
}

if [ "${1:-}" != --watch ]; then
  verify_once
  exit
fi

if [ "$POD_NAMESPACE" != games ]; then
  verify_once
  while true; do sleep 3600; done
fi

while true; do
  if ! verify_once; then
    echo "Factorio save integrity verification failed." >&2
  fi
  sleep 300
done

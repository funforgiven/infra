#!/bin/sh
set -eu

verify_once() {
  found=false
  for save in /factorio/saves/*.zip; do
    if [ ! -f "$save" ]; then
      continue
    fi
    found=true
    unzip -t "$save" >/dev/null
  done
  [ "$found" = true ]
}

if [ "${1:-}" != --watch ]; then
  verify_once
  exit
fi

while true; do
  verify_once
  sleep 300
done

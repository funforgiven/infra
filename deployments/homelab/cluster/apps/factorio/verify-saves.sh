#!/bin/sh
set -eu

verify_once() {
  found=false
  valid=true
  for save in /factorio/saves/*.zip; do
    if [ ! -f "$save" ]; then
      continue
    fi
    found=true
    if ! unzip -t "$save" >/dev/null; then
      valid=false
    fi
  done
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

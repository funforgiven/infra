#!/bin/sh
set -eu

# A short, bounded maintenance window gives the backup sidecar a consistent
# database and repository filesystem. The watchdog always reopens the service.
child=
control=${BACKUP_CONTROL:-/control}
stop_child() {
  kill -TERM "-$child" 2>/dev/null || true
  # A stuck application must not leave a permanent maintenance window.
  (sleep 45; kill -KILL "-$child" 2>/dev/null || true) &
  watchdog=$!
  wait "$child" 2>/dev/null || true
  # Git subprocesses must also stop before the backup marker is published.
  kill -KILL "-$child" 2>/dev/null || true
  kill "$watchdog" 2>/dev/null || true
  wait "$watchdog" 2>/dev/null || true
  child=
}
cleanup() {
  if test -n "$child"; then
    stop_child
  fi
  rm -f "$control/paused"
}
trap cleanup EXIT
trap 'exit 143' TERM
trap 'exit 130' INT

while :; do
  setsid "$@" &
  child=$!
  while kill -0 "$child" 2>/dev/null; do
    if test -s "$control/request"; then
      read -r deadline nonce < "$control/request" || continue
      case "$deadline" in ''|*[!0-9]*) sleep 1; continue;; esac
      if test "$(date +%s)" -lt "$deadline"; then
        stop_child
        printf '%s\n' "$nonce" > "$control/paused.next"
        mv "$control/paused.next" "$control/paused"
        while test -s "$control/request" && test "$(date +%s)" -lt "$deadline"; do
          read -r _next_deadline next_nonce < "$control/request" || break
          test "$next_nonce" = "$nonce" || break
          sleep 1
        done
        rm -f "$control/paused"
        break
      fi
    fi
    sleep 1
  done
  if test -n "$child"; then
    # Unexpected application exits belong to Kubernetes restart handling.
    wait "$child"
    exit 1
  fi
done

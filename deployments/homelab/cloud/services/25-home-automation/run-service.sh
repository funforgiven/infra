#!/bin/sh
# Keep PID 1 alive while an application is gracefully stopped for a local backup.
set -eu
name="$1"
shift
child=
control="${CONTROL_DIRECTORY:-/control}"
cleanup() {
  rm -f "$control/$name.paused" "$control/$name.running"
  if test -n "$child"; then
    kill -TERM "$child" 2>/dev/null || true
    wait "$child" || true
  fi
}
trap cleanup EXIT
trap 'exit 0' INT TERM

paused() {
  test -f "$control/pause" || return 1
  # Fail open after the backup controller dies; never leave the house paused.
  lease="$(cat "$control/pause" 2>/dev/null || echo 0)"
  deadline="${lease%%:*}"
  test "$(date +%s)" -lt "$deadline"
}

while :; do
  if paused; then
    printf '%s' "$lease" > "$control/$name.paused"
    sleep 1
    continue
  fi
  rm -f "$control/$name.paused"
  "$@" &
  child=$!
  touch "$control/$name.running"
  while kill -0 "$child" 2>/dev/null; do
    if paused; then
      kill -TERM "$child" 2>/dev/null || true
      count=0
      while kill -0 "$child" 2>/dev/null; do
        count=$((count + 1))
        if test "$count" -ge 90; then
          # A forced shutdown is not a valid recovery point.
          touch "$control/$name.failed"
          kill -KILL "$child" 2>/dev/null || true
          break
        fi
        sleep 1
      done
      break
    fi
    sleep 1
  done
  status=0
  wait "$child" || status=$?
  child=
  rm -f "$control/$name.running"
  if paused; then
    case "$status" in 0|130|143) ;; *) touch "$control/$name.failed" ;; esac
  else
    # Let Kubernetes restart unexpected failures, with its normal backoff.
    test "$status" -ne 0 || status=1
    exit "$status"
  fi
done

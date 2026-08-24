set -euo pipefail

readonly application_stop_timeout_seconds="${APPLICATION_STOP_TIMEOUT_SECONDS:-}"

if ! [[ "$application_stop_timeout_seconds" =~ ^[1-9][0-9]*$ ]]; then
  printf 'APPLICATION_STOP_TIMEOUT_SECONDS must be a positive integer\n' >&2
  exit 78
fi

usage() {
  printf 'usage: funforgiven-session-shutdown logout|reboot|poweroff\n' >&2
  exit 64
}

validate_action() {
  case "$1" in
    logout | reboot | poweroff) ;;
    *) usage ;;
  esac
}

require_graphical_session() {
  if ! systemctl --user --quiet is-active niri.service; then
    printf 'cannot exit the session: niri.service is not active\n' >&2
    exit 1
  fi

  if ! systemctl --user --quiet is-active graphical-session.target; then
    printf 'cannot exit the session: graphical-session.target is not active\n' >&2
    exit 1
  fi
}

stop_applications() {
  # Launcher and autostart applications live in app-graphical.slice. Keeping
  # the compositor, portals, shell, and user bus alive while this slice stops
  # gives applications a real opportunity to save their state after SIGTERM.
  # Do not stop app.slice: it also owns unrelated user workloads such as
  # rootless containers and Niri-created terminal scopes.
  local stop_status

  if timeout \
    --foreground \
    --signal=TERM \
    --kill-after=1s \
    "${application_stop_timeout_seconds}s" \
    systemctl --user --job-mode=replace-irreversibly stop app-graphical.slice; then
    return
  else
    stop_status=$?
  fi

  case "$stop_status" in
    124 | 137)
      printf \
        'application shutdown exceeded %ss; killing remaining graphical applications\n' \
        "$application_stop_timeout_seconds" >&2
      systemctl --user kill --kill-whom=all --signal=SIGKILL app-graphical.slice
      ;;
    *)
      printf 'failed to stop app-graphical.slice (status %s)\n' "$stop_status" >&2
      return "$stop_status"
      ;;
  esac

  if timeout \
    --foreground \
    --signal=TERM \
    --kill-after=1s \
    1s \
    systemctl --user --job-mode=replace-irreversibly stop app-graphical.slice; then
    return
  else
    stop_status=$?
  fi

  case "$stop_status" in
    124 | 137)
      printf 'app-graphical.slice did not settle after SIGKILL\n' >&2
      return 1
      ;;
    *)
      printf 'failed to settle app-graphical.slice after SIGKILL (status %s)\n' "$stop_status" >&2
      return "$stop_status"
      ;;
  esac
}

stop_graphical_session() {
  # Logout has no pending machine transaction to own the final teardown, so
  # keep the coordinator alive until Niri's shutdown target completes.
  systemctl --user --job-mode=replace-irreversibly start niri-shutdown.target
}

request_system_shutdown() {
  local requested_action="$1"

  # Starting the machine transaction before this point lets logind tear down
  # Wayland and portals concurrently with application shutdown. Drain the
  # graphical application slice first; only then hand control to logind.
  stop_applications
  exec systemctl --check-inhibitors=no "$requested_action"
}

if (( $# != 1 )); then
  usage
fi

readonly action="$1"
validate_action "$action"
require_graphical_session

if [[ "$action" == "logout" ]]; then
  stop_applications
  stop_graphical_session
  exit 0
fi

request_system_shutdown "$action"

#!/usr/bin/env bash
# Runs the generated PipeWire/WirePlumber configuration in an isolated session:
# bridges follow their fixed outputs without fallback, and funforgiven-audioctl
# moves a stream with a route that WirePlumber restores.
set -euo pipefail

: "${PIPEWIRE_SHARE:?}" "${PIPEWIRE_CONFIG:?}" "${WIREPLUMBER_DATA_DIRS:?}" "${CHANNELS:?}"

work=$TMPDIR/audio
export HOME=$work/home XDG_RUNTIME_DIR=$work/runtime XDG_STATE_HOME=$work/state XDG_CONFIG_HOME=$work/config
export PIPEWIRE_CONFIG_DIR=$work/pipewire
export DBUS_SESSION_BUS_ADDRESS=unix:path=$work/none DBUS_SYSTEM_BUS_ADDRESS=unix:path=$work/none
mkdir -p "$HOME" "$XDG_RUNTIME_DIR" "$XDG_STATE_HOME" "$XDG_CONFIG_HOME" "$PIPEWIRE_CONFIG_DIR"
chmod 0700 "$XDG_RUNTIME_DIR"
ln -s "$PIPEWIRE_SHARE"/*.conf "$PIPEWIRE_CONFIG_DIR/"
ln -s "$PIPEWIRE_CONFIG" "$PIPEWIRE_CONFIG_DIR/pipewire.conf.d"

pids=()
wp_pid=""
client_pid=""
cleanup() { kill "${pids[@]}" ${wp_pid:+"$wp_pid"} ${client_pid:+"$client_pid"} 2>/dev/null || true; }
trap cleanup EXIT

fail() {
  printf 'audio integration failure: %s\n' "$1" >&2
  tail -n 60 "$work"/*.log "$XDG_STATE_HOME"/wireplumber/* >&2 || true
  exit 1
}

wait_for() {
  local description=$1
  shift
  for _ in $(seq 200); do
    "$@" && return 0
    sleep 0.05
  done
  fail "timed out waiting for $description"
}

channel() { jq -r --arg id "$1" --arg key "$2" '.[] | select(.id == $id) | .[$key]' <<<"$CHANNELS"; }

node_ref() {
  pw-dump | jq -r --arg name "$1" \
    '.[] | select(.type == "PipeWire:Interface:Node" and .info.props["node.name"] == $name) | "\(.id) \(.info.props["object.serial"])"'
}

# linked OUTPUT_NODE [INPUT_NODE]: OUTPUT_NODE feeds INPUT_NODE (or anything).
linked() {
  pw-dump | jq -e --arg out "$1" --arg in "${2-}" '
    (map(select(.type == "PipeWire:Interface:Node")) | map({key: (.id | tostring), value: .info.props["node.name"]}) | from_entries) as $names
    | any(.[] | select(.type == "PipeWire:Interface:Link") | .info;
        $names[."output-node-id" | tostring] == $out
        and ($in == "" or $names[."input-node-id" | tostring] == $in))
  ' >/dev/null
}

create_output() {
  pw-cli create-node adapter "{ factory.name = support.null-audio-sink node.name = \"$1\" media.class = Audio/Sink object.linger = true audio.position = [ FL FR ] }" >/dev/null
}

start_wireplumber() {
  XDG_DATA_DIRS=$WIREPLUMBER_DATA_DIRS wireplumber -p policy >>"$work/wireplumber.log" 2>&1 &
  wp_pid=$!
}

start_client() {
  pw-cat --playback --raw --rate 48000 --channels 2 --format s16 \
    --properties '{ application.id = "funforgiven.test" application.name = "Test" node.name = "funforgiven.test.stream" }' \
    /dev/zero >>"$work/client.log" 2>&1 &
  client_pid=$!
}

expect_exit() {
  local expected=$1 status=0
  shift
  funforgiven-audioctl "$@" 2>/dev/null || status=$?
  [[ $status == "$expected" ]] || fail "audioctl $* exited $status, expected $expected"
}

pipewire >"$work/pipewire.log" 2>&1 &
pids+=($!)
wait_for "PipeWire socket" test -S "$XDG_RUNTIME_DIR/pipewire-0"

create_output "$(channel system output)"
create_output "$(channel game output)"
start_wireplumber

for id in system game; do
  wait_for "$id bridge on its output" linked "$(channel "$id" bridgeName)" "$(channel "$id" output)"
done
sleep 1
for id in voice music; do
  [[ -n $(node_ref "$(channel "$id" bridgeName)") ]] || fail "$id bridge is missing"
  ! linked "$(channel "$id" bridgeName)" || fail "$id bridge fell back to another output"
done

create_output "$(channel voice output)"
wait_for "voice bridge after its output appears" linked "$(channel voice bridgeName)" "$(channel voice output)"

start_client
wait_for "new stream on System" linked funforgiven.test.stream "$(channel system sinkName)"
read -r stream_id stream_serial < <(node_ref funforgiven.test.stream)
read -r bridge_id bridge_serial < <(node_ref "$(channel game bridgeName)")

expect_exit 64 move-stream "$stream_id" "$stream_serial" nowhere
expect_exit 64 move-stream "0$stream_id" "$stream_serial" game
expect_exit 64 move-stream "$stream_id"
expect_exit 1 move-stream "$stream_id" "$((stream_serial + 1000))" game
expect_exit 1 move-stream "$bridge_id" "$bridge_serial" system
funforgiven-audioctl --help >/dev/null

funforgiven-audioctl move-stream "$stream_id" "$stream_serial" game
wait_for "stream moved to Game" linked funforgiven.test.stream "$(channel game sinkName)"
wait_for "saved stream route" grep -qE '^Output/Audio:application\.id:funforgiven\.test=.*"target"' \
  "$XDG_STATE_HOME/wireplumber/stream-properties"

kill "$client_pid"
wait "$client_pid" || true
kill "$wp_pid"
wait "$wp_pid" || true
start_wireplumber
wait_for "system bridge after restart" linked "$(channel system bridgeName)" "$(channel system output)"
start_client
wait_for "restored stream route to Game" linked funforgiven.test.stream "$(channel game sinkName)"

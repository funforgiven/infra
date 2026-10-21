#!/usr/bin/env bash

set -euo pipefail

readonly program_name="${0##*/}"
readonly max_global_id="4294967294"
readonly max_object_serial="18446744073709551615"
readonly move_request_key="funforgiven.audio.move-output-target"
readonly move_ack_key="funforgiven.audio.move-output-target-ack"
readonly move_error_key="funforgiven.audio.move-output-target-error"
readonly reset_request_key="funforgiven.audio.reset-output-target"
readonly reset_commit_key="funforgiven.audio.reset-output-target-commit"
readonly reset_ack_key="funforgiven.audio.reset-output-target-ack"
readonly reset_error_key="funforgiven.audio.reset-output-target-error"

graph_json=""
destination_serial=""
default_metadata_serial=""
hardware_target_name=""
transaction_cleanup_enabled=false
transaction_lock_fd=""

# Set by read_node_facts.
node_count=0
node_serial=""
node_media_class=""
node_channel=""
node_kind=""
node_internal=false
node_name=""
node_virtual=false
node_disabled=false
node_error_state=false
node_policy_endpoint=false
node_device_id=""
node_device_count=0
node_resolved_count=0
node_resolved_id=""

usage() {
  cat <<'EOF'
Usage:
  funforgiven-audioctl move-stream SOURCE_ID SOURCE_SERIAL CHANNEL_ID
  funforgiven-audioctl move-bridge BRIDGE_ID BRIDGE_SERIAL CHANNEL_ID TARGET_ID TARGET_SERIAL
  funforgiven-audioctl forget-bridge-target BRIDGE_ID BRIDGE_SERIAL CHANNEL_ID

Actions:
  move-stream           Move one application stream to a logical channel.
  move-bridge           Send a logical channel to one physical output.
  forget-bridge-target  Forget a channel's saved physical output.

CHANNEL_ID must be one of: system, game, voice, music.

The IDs and object.serial values must come from the current PipeWire graph.
The command validates them again immediately before changing target.object
metadata. It does not keep routing state of its own.
EOF
}

usage_error() {
  printf '%s: error: %s\n' "$program_name" "$1" >&2
  printf "Try '%s --help' for usage.\n" "$program_name" >&2
  exit 64
}

runtime_error() {
  printf '%s: error: %s\n' "$program_name" "$1" >&2
  exit 1
}

is_canonical_uint_at_most() {
  local value=$1
  local maximum=$2
  local value_length=${#value}
  local max_length=${#maximum}
  local index
  local value_digit
  local maximum_digit

  [[ $value =~ ^(0|[1-9][0-9]*)$ ]] || return 1

  if ((value_length > max_length)); then
    return 1
  fi

  if ((value_length == max_length)); then
    for ((index = 0; index < value_length; index++)); do
      value_digit=${value:index:1}
      maximum_digit=${maximum:index:1}

      if ((value_digit < maximum_digit)); then
        return 0
      fi
      if ((value_digit > maximum_digit)); then
        return 1
      fi
    done
  fi
}

is_global_id() {
  is_canonical_uint_at_most "$1" "$max_global_id"
}

is_object_serial() {
  is_canonical_uint_at_most "$1" "$max_object_serial"
}

validate_global_id_argument() {
  local label=$1
  local value=$2

  if ! is_global_id "$value"; then
    usage_error "$label must be a decimal PipeWire global ID from 0 to $max_global_id without leading zeros; got '$value'"
  fi
}

validate_serial_argument() {
  local label=$1
  local value=$2

  if ! is_object_serial "$value"; then
    usage_error "$label must be a decimal PipeWire object.serial from 0 to $max_object_serial without leading zeros; got '$value'"
  fi
}

looks_like_lua_number() {
  local value=$1
  local decimal_pattern='^[[:space:]]*[+-]?(([0-9]+([.][0-9]*)?)|([.][0-9]+))([eE][+-]?[0-9]+)?[[:space:]]*$'
  local hexadecimal_pattern='^[[:space:]]*[+-]?0[xX](([0-9a-fA-F]+([.][0-9a-fA-F]*)?)|([.][0-9a-fA-F]+))([pP][+-]?[0-9]+)?[[:space:]]*$'

  [[ $value =~ $decimal_pattern || $value =~ $hexadecimal_pattern ]]
}

validate_channel_argument() {
  case $1 in
    system | game | voice | music) ;;
    *) usage_error "CHANNEL_ID must be exactly one of system, game, voice, or music; got '$1'" ;;
  esac
}

require_commands() {
  local command_name

  for command_name in flock jq pw-dump pw-metadata; do
    if ! command -v "$command_name" >/dev/null 2>&1; then
      runtime_error "required command '$command_name' is not available in PATH"
    fi
  done
}

acquire_channel_transaction_lock() {
  local channel_id=$1
  local lock_dir
  local lock_path

  if [[ -z ${XDG_RUNTIME_DIR:-} || $XDG_RUNTIME_DIR != /* ]]; then
    runtime_error "XDG_RUNTIME_DIR must name an absolute per-user runtime directory"
  fi
  lock_dir="$XDG_RUNTIME_DIR/funforgiven-audioctl"
  if ! mkdir -p -- "$lock_dir" || ! chmod 0700 -- "$lock_dir"; then
    runtime_error "could not prepare the audio transaction lock directory '$lock_dir'"
  fi
  lock_path="$lock_dir/$channel_id.lock"
  if ! exec {transaction_lock_fd}>"$lock_path"; then
    runtime_error "could not open the audio transaction lock for channel '$channel_id'"
  fi
  if ! flock -n "$transaction_lock_fd"; then
    exec {transaction_lock_fd}>&-
    transaction_lock_fd=""
    runtime_error "another output routing transaction is already active for channel '$channel_id'; retry after it finishes"
  fi
}

release_channel_transaction_lock() {
  if [[ -n $transaction_lock_fd ]]; then
    exec {transaction_lock_fd}>&-
    transaction_lock_fd=""
  fi
}

# Definitions shared by every query against the loaded pw-dump JSON.
# shellcheck disable=SC2016
readonly jq_prelude='
  def default_metadata:
    .[]
    | select(.type == "PipeWire:Interface:Metadata")
    | select(.props["metadata.name"] == "default");
  def subject_entries($subject):
    [default_metadata | .metadata[]? | select((.subject | tostring) == $subject)];
  def scalar:
    if type == "number" or type == "string" then tostring else "" end;
  def truthy:
    . == true or . == "true" or . == "yes" or . == 1 or . == "1";
  def live_nodes:
    [.[] | select(.type == "PipeWire:Interface:Node")];
'

try_load_graph() {
  local dump

  dump=$(pw-dump "$@" 2>/dev/null) || return 1
  jq -e 'type == "array" and all(.[]; type == "object")' \
    >/dev/null <<<"$dump" || return 1
  graph_json=$dump
}

# load_graph [PATTERN] reads the whole graph, or only the objects that pw-dump
# matches against PATTERN. Polling uses "default" to read just the default
# metadata object instead of every node, port, and link.
load_graph() {
  if ! try_load_graph "$@"; then
    runtime_error "pw-dump could not read the PipeWire graph; confirm that the user PipeWire service is running"
  fi
}

capture_default_metadata() {
  local result

  if ! result=$(jq -r "$jq_prelude"'
    [default_metadata | .props["object.serial"] | scalar]
    | if length == 1 then .[0] else "count:\(length)" end
  ' <<<"$graph_json"); then
    runtime_error "could not inspect the default PipeWire metadata object"
  fi
  if [[ $result == count:* ]]; then
    runtime_error "expected exactly one live PipeWire metadata object named 'default', found ${result#count:}"
  fi
  if ! is_object_serial "$result"; then
    runtime_error "the default PipeWire metadata object has no valid object.serial"
  fi

  default_metadata_serial=$result
}

require_same_default_metadata() {
  local expected_serial=$1

  capture_default_metadata
  if [[ $default_metadata_serial != "$expected_serial" ]]; then
    runtime_error "the default PipeWire metadata object restarted during the action; refresh the mixer and retry"
  fi
}

target_metadata_is() {
  local subject_id=$1
  local expected_type=$2
  local expected_value=$3

  jq -e \
    --arg subject "$subject_id" \
    --arg expected_type "$expected_type" \
    --arg expected_value "$expected_value" "$jq_prelude"'
    subject_entries($subject)
    | map(select(.key == "target.object"))
    | length == 1
      and .[0].type == $expected_type
      and (.[0].value | tostring) == $expected_value
  ' <<<"$graph_json" >/dev/null
}

# A transaction publishes REQUEST, waits for WirePlumber to acknowledge it as
# "NONCE:armed", publishes the commit, and waits for the final "NONCE"
# acknowledgement. WirePlumber reports failures as "NONCE:CODE" under the error
# key. Every control value is tagged with the nonce so cleanup removes only
# state owned by this process.
tx_kind=""
tx_action=""
tx_channel=""
tx_subject=""
tx_nonce=""
tx_request=""
tx_request_key=""
tx_owned_commit_key=""
tx_ack_key=""
tx_error_key=""

# Set by read_transaction_state.
tx_state_keys=""
tx_state_request_present=false
tx_state_request_owned=false
tx_state_commit_owned=false
tx_state_ack=""
tx_state_error=""

prepare_transaction() {
  tx_kind=$1
  tx_subject=$2
  tx_nonce=$3
  tx_request=$4

  case $tx_kind in
    move)
      tx_action="output move"
      tx_request_key=$move_request_key
      tx_owned_commit_key=""
      tx_ack_key=$move_ack_key
      tx_error_key=$move_error_key
      ;;
    reset)
      tx_action="output reset"
      tx_request_key=$reset_request_key
      tx_owned_commit_key=$reset_commit_key
      tx_ack_key=$reset_ack_key
      tx_error_key=$reset_error_key
      ;;
    *) runtime_error "unknown transaction kind '$tx_kind'" ;;
  esac
}

# Reads this transaction's control metadata from the loaded graph into the
# tx_state_* globals.
read_transaction_state() {
  local state

  state=$(jq -r \
    --arg subject "$tx_subject" \
    --arg nonce "$tx_nonce" \
    --arg request "$tx_request" \
    --arg request_key "$tx_request_key" \
    --arg commit_key "$tx_owned_commit_key" \
    --arg ack_key "$tx_ack_key" \
    --arg error_key "$tx_error_key" "$jq_prelude"'
    def string_value($entries; $key):
      [$entries[] | select(.key == $key)]
      | if length == 1 and .[0].type == "Spa:String" then .[0].value else null end;

    subject_entries($subject) as $entries
    | [$entries[] | .key] as $keys
    | [
        $entries[]
        | select(.key == $error_key and .type == "Spa:String")
        | .value | tostring
        | select(startswith($nonce + ":"))
        | ltrimstr($nonce + ":")
      ] as $errors
    | if ($errors | length) > 1 then
        error("ambiguous transaction error metadata")
      else
        @sh "tx_state_keys=\(
          [$request_key, $commit_key, $ack_key, $error_key]
          | map(select(. != "" and (. as $key | $keys | index($key)) != null))
          | join(" "))",
        @sh "tx_state_request_present=\(($keys | index($request_key)) != null)",
        @sh "tx_state_request_owned=\(string_value($entries; $request_key) == $request)",
        @sh "tx_state_commit_owned=\(
          $commit_key != "" and string_value($entries; $commit_key) == $nonce)",
        @sh "tx_state_ack=\(string_value($entries; $ack_key) // "" | tostring)",
        @sh "tx_state_error=\($errors[0] // "")"
      end
  ' <<<"$graph_json") || return 1
  eval "$state"
}

transaction_controls_owned() {
  [[ $tx_state_request_owned == true \
    || $tx_state_commit_owned == true \
    || $tx_state_ack == "$tx_nonce" \
    || $tx_state_ack == "$tx_nonce:armed" \
    || -n $tx_state_error ]]
}

try_clear_owned_transaction_controls() {
  local expect_owned_request=false
  local _cleanup_attempt

  for _cleanup_attempt in {1..20}; do
    if ! try_load_graph default || ! read_transaction_state; then
      sleep 0.02
      continue
    fi

    # WirePlumber restores the active request after rejecting a conflicting
    # one, so wait for it whenever this transaction still owned the policy.
    if [[ $tx_state_request_owned == true ]]; then
      expect_owned_request=false
      pw-metadata -n default -d -- "$tx_subject" "$tx_request_key" \
        >/dev/null 2>&1 || true
    elif [[ $tx_state_request_present == true ]] \
      && { [[ $tx_state_ack == "$tx_nonce" || $tx_state_ack == "$tx_nonce:armed" ]] \
        || [[ -n $tx_state_error && $tx_state_error != busy ]] \
        || [[ $expect_owned_request == true ]]; }; then
      expect_owned_request=true
    fi
    if [[ $tx_state_commit_owned == true ]]; then
      pw-metadata -n default -d -- "$tx_subject" "$tx_owned_commit_key" \
        >/dev/null 2>&1 || true
    fi
    if [[ $tx_state_ack == "$tx_nonce" || $tx_state_ack == "$tx_nonce:armed" ]]; then
      pw-metadata -n default -d -- "$tx_subject" "$tx_ack_key" \
        >/dev/null 2>&1 || true
    fi
    if [[ -n $tx_state_error ]]; then
      pw-metadata -n default -d -- "$tx_subject" "$tx_error_key" \
        >/dev/null 2>&1 || true
    fi

    sleep 0.02
    if try_load_graph default && read_transaction_state \
      && ! transaction_controls_owned; then
      if [[ $expect_owned_request == true \
        && $tx_state_request_present == true ]]; then
        continue
      fi
      return 0
    fi
  done
  return 1
}

arm_transaction_cleanup() {
  transaction_cleanup_enabled=true
  trap 'transaction_cleanup_trap "$?"' EXIT
  trap 'transaction_cleanup_trap 130' INT
  trap 'transaction_cleanup_trap 143' TERM
}

transaction_cleanup_trap() {
  local status=$1

  trap - EXIT INT TERM
  if [[ $transaction_cleanup_enabled == true ]] \
    && ! try_clear_owned_transaction_controls; then
    printf '%s: error: failed to clean interrupted %s transaction %s\n' \
      "$program_name" "$tx_kind" "$tx_nonce" >&2
    if ((status == 0)); then
      status=1
    fi
  fi
  transaction_cleanup_enabled=false
  exit "$status"
}

finish_transaction() {
  if ! try_clear_owned_transaction_controls; then
    runtime_error "failed to clear durable $tx_action controls owned by nonce $tx_nonce"
  fi
  transaction_cleanup_enabled=false
  trap - EXIT INT TERM
}

fail_transaction() {
  finish_transaction
  runtime_error "$1"
}

transaction_error_message() {
  local code=$1
  local target_id=$2
  local action=$tx_action
  local channel_id=$tx_channel

  case $code in
    state-save)
      printf "WirePlumber could not durably persist the %s for channel '%s'; the previous target was restored" "$action" "$channel_id"
      ;;
    metadata-publish | ack-publish)
      printf "WirePlumber could not publish the completed %s for channel '%s'; durable state and the live target were rolled back" "$action" "$channel_id"
      ;;
    arm-publish)
      printf "WirePlumber could not arm the %s for channel '%s'" "$action" "$channel_id"
      ;;
    rollback-live)
      printf "WirePlumber restored durable state after a failed %s for channel '%s' but could not restore the live target metadata; refresh the mixer and inspect WirePlumber before retrying" "$action" "$channel_id"
      ;;
    rollback-save)
      printf "WirePlumber restored the live target after a failed %s for channel '%s' but could not restore durable state; inspect the WirePlumber state directory before retrying" "$action" "$channel_id"
      ;;
    rollback-incomplete)
      printf "WirePlumber could not restore either live target metadata or durable state after a failed %s for channel '%s'; inspect WirePlumber before retrying" "$action" "$channel_id"
      ;;
    unsafe-target)
      printf "WirePlumber rejected target node ID %s as unavailable or unsafe and restored the previous output" "$target_id"
      ;;
    invalid-target)
      printf "WirePlumber rejected malformed target metadata for channel '%s' and restored the previous output" "$channel_id"
      ;;
    invalid-commit)
      printf "WirePlumber rejected the %s commit for channel '%s'" "$action" "$channel_id"
      ;;
    superseded | busy)
      printf "the %s for channel '%s' was blocked or superseded by another routing action" "$action" "$channel_id"
      ;;
    stale-identity)
      printf "the channel '%s' bridge identity changed during the %s; refresh the mixer and retry" "$channel_id" "$action"
      ;;
    *)
      printf "WirePlumber rejected the %s for channel '%s' with error '%s'" "$action" "$channel_id" "$code"
      ;;
  esac
}

# await_transaction PHASE TARGET_ID polls only the default metadata object
# until WirePlumber reports PHASE (armed or acknowledged) or an error.
await_transaction() {
  local phase=$1
  local target_id=$2
  local metadata_serial=$3
  local _attempt

  for _attempt in {1..60}; do
    load_graph default
    require_same_default_metadata "$metadata_serial"
    if ! read_transaction_state; then
      fail_transaction "could not inspect the $tx_action state for channel '$tx_channel'"
    fi
    if [[ -n $tx_state_error ]]; then
      fail_transaction "$(transaction_error_message "$tx_state_error" "$target_id")"
    fi
    case $phase in
      armed)
        if [[ $tx_state_request_owned == true \
          && $tx_state_ack == "$tx_nonce:armed" ]]; then
          return 0
        fi
        if [[ $tx_state_request_present == true \
          && $tx_state_request_owned != true ]]; then
          fail_transaction "$(transaction_error_message busy "$target_id")"
        fi
        ;;
      acknowledged)
        if [[ $tx_state_ack == "$tx_nonce" ]]; then
          return 0
        fi
        ;;
    esac
    sleep 0.05
  done

  if [[ $phase == armed ]]; then
    fail_transaction "WirePlumber did not arm the $tx_action for channel '$tx_channel'"
  fi
  fail_transaction "WirePlumber did not acknowledge the $tx_action for channel '$tx_channel'"
}

# Reads one node, its name resolution, and its device backing from the loaded
# graph into the node_* globals with a single jq pass.
read_node_facts() {
  local node_id=$1
  local facts

  facts=$(jq -r --arg id "$node_id" "$jq_prelude"'
    live_nodes as $nodes
    | [$nodes[] | select((.id | tostring) == $id)] as $matches
    | ($matches[0] // {}) as $node
    | ($node.info.props // {}) as $p
    | ($p["node.name"] // "" | tostring) as $name
    | ($p["device.id"] | scalar) as $device_id
    | [
        $nodes[]
        | select($name != "")
        | select(.info.props["node.name"] == $name or .info.props["object.path"] == $name)
        | .id | tostring
      ] as $resolved
    # UCM SplitPCM outputs are device-backed ALSA loopbacks, not filters, so
    # a link-group alone does not make them a policy endpoint.
    | @sh "node_count=\($matches | length)",
      @sh "node_serial=\($p["object.serial"] | scalar)",
      @sh "node_media_class=\($p["media.class"] // "" | tostring)",
      @sh "node_channel=\($p["funforgiven.audio.channel"] // "" | tostring)",
      @sh "node_kind=\($p["funforgiven.audio.kind"] // "" | tostring)",
      @sh "node_internal=\($p | has("funforgiven.audio.channel") or has("funforgiven.audio.kind"))",
      @sh "node_name=\($name)",
      @sh "node_virtual=\($p["node.virtual"] | truthy)",
      @sh "node_disabled=\(($p["node.disabled"] | truthy) or ($p["device.disabled"] | truthy))",
      @sh "node_error_state=\($node.info.state == "error")",
      @sh "node_policy_endpoint=\(
        ($p["wireplumber.is-virtual"] | truthy)
        or ($p["wireplumber.is-fallback"] | truthy)
        or ($p["bluez5.loopback"] | truthy)
        or (($p | has("node.link-group")) and (
          $p["device.api"] == "alsa"
          and $p["api.alsa.pcm.stream"] == "playback"
          and ($p["api.alsa.split.name"] | type == "string" and length > 0)
          and ($p["api.alsa.split.position"] | type == "string" and length > 0)
        | not))
        or ($p | has("filter.smart"))
        or ($p | has("filter.smart.name"))
        or ($p | has("filter.smart.target"))
        or ($p["factory.name"] == "support.null-audio-sink"))",
      @sh "node_device_id=\($device_id)",
      @sh "node_device_count=\(
        [.[] | select(.type == "PipeWire:Interface:Device" and (.id | tostring) == $device_id)]
        | length)",
      @sh "node_resolved_count=\($resolved | length)",
      @sh "node_resolved_id=\($resolved[0] // "")"
  ' <<<"$graph_json") || return 1
  eval "$facts"
}

expect_live_node() {
  local label=$1
  local expected_id=$2
  local expected_serial=$3

  if ! read_node_facts "$expected_id"; then
    runtime_error "could not inspect $label node ID $expected_id in the pw-dump JSON"
  fi

  case $node_count in
    0)
      runtime_error "$label node ID $expected_id is no longer live; refresh the mixer and try again"
      ;;
    1) ;;
    *)
      runtime_error "PipeWire reported $node_count nodes with ID $expected_id; refusing an ambiguous $label"
      ;;
  esac

  if ! is_object_serial "$node_serial"; then
    runtime_error "$label node ID $expected_id has no valid unsigned 64-bit object.serial in the PipeWire graph"
  fi

  if [[ $node_serial != "$expected_serial" ]]; then
    runtime_error "$label node ID $expected_id is stale or was reused: expected object.serial $expected_serial, found $node_serial"
  fi
}

# Uses the node_* facts of the node most recently read.
validate_unique_name_resolution() {
  local label=$1
  local expected_id=$2

  if [[ $node_resolved_count != 1 ]]; then
    runtime_error "$label node.name '$node_name' resolves to $node_resolved_count live nodes through node.name/object.path; refusing an ambiguous identity"
  fi
  if [[ $node_resolved_id != "$expected_id" ]]; then
    runtime_error "$label node.name '$node_name' resolves to node ID $node_resolved_id instead of selected node ID $expected_id"
  fi
}

validate_source_stream() {
  local source_id=$1
  local source_serial=$2

  expect_live_node "source stream" "$source_id" "$source_serial"

  if [[ $node_media_class != "Stream/Output/Audio" ]]; then
    runtime_error "source node ID $source_id is '$node_media_class', not a Stream/Output/Audio playback stream"
  fi

  if [[ $node_internal == true ]]; then
    runtime_error "source node ID $source_id is an internal audio-channel node, not an application playback stream"
  fi
}

resolve_logical_sink() {
  local channel_id=$1
  local matches
  local count
  local sink_id
  local expected_sink_name

  if ! matches=$(jq -r --arg channel "$channel_id" "$jq_prelude"'
    [
      live_nodes[]
      | select(.info.props["funforgiven.audio.channel"] == $channel)
      | select(.info.props["funforgiven.audio.kind"] == "sink")
      | .id | tostring
    ]
    | "\(length) \(.[0] // "")"
  ' <<<"$graph_json"); then
    runtime_error "could not resolve the marked logical sink for channel '$channel_id'"
  fi
  read -r count sink_id <<<"$matches"

  case $count in
    0)
      runtime_error "the marked logical sink for channel '$channel_id' is not live"
      ;;
    1) ;;
    *)
      runtime_error "found $count marked logical sinks for channel '$channel_id'; refusing an ambiguous destination"
      ;;
  esac

  if ! is_global_id "$sink_id"; then
    runtime_error "the logical sink for channel '$channel_id' has no valid PipeWire node ID"
  fi

  if ! read_node_facts "$sink_id"; then
    runtime_error "could not decode the logical sink for channel '$channel_id'"
  fi

  if ! is_object_serial "$node_serial"; then
    runtime_error "the logical sink for channel '$channel_id' has no valid unsigned object.serial"
  fi
  destination_serial=$node_serial

  if [[ $node_media_class != "Audio/Sink" ]]; then
    runtime_error "the node marked as channel '$channel_id' sink is '$node_media_class', not Audio/Sink"
  fi

  if [[ $node_virtual != true ]]; then
    runtime_error "the node marked as channel '$channel_id' sink is not virtual; refusing an unsafe destination"
  fi

  if [[ -z $node_name ]]; then
    runtime_error "the logical sink for channel '$channel_id' has no stable node.name"
  fi

  expected_sink_name=${expected_sink_names[$channel_id]-}
  if [[ -z $expected_sink_name || $node_name != "$expected_sink_name" ]]; then
    runtime_error "the marked '$channel_id' sink has node.name '$node_name', expected '$expected_sink_name'"
  fi
  validate_unique_name_resolution "channel '$channel_id' sink" "$sink_id"
}

validate_bridge() {
  local bridge_id=$1
  local bridge_serial=$2
  local channel_id=$3
  local expected_bridge_name

  expect_live_node "bridge" "$bridge_id" "$bridge_serial"

  if [[ $node_channel != "$channel_id" || $node_kind != "bridge" ]]; then
    runtime_error "node ID $bridge_id is not the marked '$channel_id' bridge"
  fi

  if [[ $node_media_class != "Stream/Output/Audio" ]]; then
    runtime_error "marked bridge node ID $bridge_id is '$node_media_class', not Stream/Output/Audio"
  fi

  if [[ -z $node_name ]]; then
    runtime_error "marked bridge node ID $bridge_id has no stable node.name"
  fi

  expected_bridge_name=${expected_bridge_names[$channel_id]-}
  if [[ -z $expected_bridge_name || $node_name != "$expected_bridge_name" ]]; then
    runtime_error "the marked '$channel_id' bridge has node.name '$node_name', expected '$expected_bridge_name'"
  fi
  validate_unique_name_resolution "channel '$channel_id' bridge" "$bridge_id"
}

target_would_create_cycle() {
  local target_id=$1
  local bridge_id=$2

  jq -e --arg start "$target_id" --arg goal "$bridge_id" '
    def endpoint($link; $field; $property):
      $link.info[$field] // $link.info.props[$property];

    def canonical_global_id:
      if type == "number" then
        . >= 0 and . <= 4294967294 and floor == .
      elif type == "string" then
        test("^(0|[1-9][0-9]*)$")
        and (
          length < 10
          or (length == 10 and . <= "4294967294")
        )
      else
        false
      end;

    def live_global_id($node_ids):
      . as $id
      | ($id | canonical_global_id)
        and (($node_ids | index($id | tostring)) != null);

    def reaches($edges; $start; $goal):
      def visit($pending; $seen):
        if ($pending | length) == 0 then
          false
        else
          $pending[0] as $current
          | if $current == $goal then
              true
            elif ($seen | index($current)) != null then
              visit($pending[1:]; $seen)
            else
              [ $edges[] | select(.from == $current) | .to ] as $next
              | visit($pending[1:] + $next; $seen + [$current])
            end
        end;
      visit([$start]; []);

    [ .[] | select(.type == "PipeWire:Interface:Node") ] as $nodes
    | [ $nodes[] | .id | tostring ] as $node_ids
    | [ .[] | select(.type == "PipeWire:Interface:Link") ] as $links
    | if any($nodes[]; (.id | canonical_global_id | not))
      or (($node_ids | unique | length) != ($node_ids | length))
      or any(
        $links[];
        (endpoint(.; "output-node-id"; "link.output.node") | live_global_id($node_ids) | not)
        or (endpoint(.; "input-node-id"; "link.input.node") | live_global_id($node_ids) | not)
      ) then
        error("the PipeWire graph has malformed, stale, or ambiguous structured link endpoints")
      else
        [
          $links[]
          | {
              from: (endpoint(.; "output-node-id"; "link.output.node") | tostring),
              to: (endpoint(.; "input-node-id"; "link.input.node") | tostring)
            }
        ] as $link_edges
        | [
            .[] as $sink
            | select($sink.type == "PipeWire:Interface:Node")
            | select($sink.info.props["funforgiven.audio.kind"] == "sink")
            | .[] as $bridge
            | select($bridge.type == "PipeWire:Interface:Node")
            | select($bridge.info.props["funforgiven.audio.kind"] == "bridge")
            | select(
                $bridge.info.props["funforgiven.audio.channel"]
                == $sink.info.props["funforgiven.audio.channel"]
              )
            | { from: ($sink.id | tostring), to: ($bridge.id | tostring) }
          ] as $channel_edges
        | reaches($link_edges + $channel_edges; $start; $goal)
      end
  ' <<<"$graph_json"
}

target_has_available_routes() {
  local target_id=$1
  local device_id=$2

  jq -e --arg target_id "$target_id" --arg device_id "$device_id" '
    def canonical_route_device:
      if type == "number" then
        if . >= 0 and . <= 2147483647 and floor == . then tostring else null end
      elif type == "string" and test("^(0|[1-9][0-9]*)$") then
        if length < 10 or (length == 10 and . <= "2147483647") then . else null end
      else
        null
      end;

    def route_is_available:
      ((.available // "unknown") | tostring | ascii_downcase) != "no";

    first(
      .[]
      | select(.type == "PipeWire:Interface:Node")
      | select((.id | tostring) == $target_id)
    ) as $target
    | ($target.info.props["card.profile.device"] // null | canonical_route_device) as $profile_device
    | if $profile_device == null then
        true
      else
        [
          .[]
          | select(.type == "PipeWire:Interface:Device")
          | select((.id | tostring) == $device_id)
        ] as $devices
        | if ($devices | length) != 1 then
            error("target device identity changed during route validation")
          else
            ($devices[0].info.params.Route // []) as $active_routes
            | ($devices[0].info.params.EnumRoute // []) as $enumerated_routes
            | if ($active_routes | type) != "array" or
                ($enumerated_routes | type) != "array" then
                error("target device route parameters are malformed")
              else
                [
                  $active_routes[]
                  | select((.device | canonical_route_device) == $profile_device)
                ] as $active_matches
                | if ($active_matches | length) > 0 then
                    ($active_matches[0] | route_is_available)
                  else
                    [
                      $enumerated_routes[]
                      | select(any(
                          (.devices // [])[];
                          (. | canonical_route_device) == $profile_device
                        ))
                    ] as $enumerated_matches
                    | ($enumerated_matches | length) == 0 or
                      any($enumerated_matches[]; route_is_available)
                  end
              end
          end
      end
  ' <<<"$graph_json" >/dev/null
}

validate_hardware_target() {
  local bridge_id=$1
  local target_id=$2
  local target_serial=$3
  local device_id
  local availability_status
  local cycle_status

  expect_live_node "target" "$target_id" "$target_serial"

  if [[ $target_id == "$bridge_id" ]]; then
    runtime_error "bridge node ID $bridge_id cannot target itself"
  fi

  if [[ $node_internal == true ]]; then
    runtime_error "target node ID $target_id is an internal logical sink or bridge"
  fi

  if [[ $node_media_class != "Audio/Sink" ]]; then
    runtime_error "target node ID $target_id is '$node_media_class', not a live Audio/Sink"
  fi

  if [[ $node_disabled == true ]]; then
    runtime_error "target node ID $target_id is disabled or unavailable"
  fi

  if [[ $node_error_state == true ]]; then
    runtime_error "target node ID $target_id is in the PipeWire error state"
  fi

  if [[ $node_virtual == true ]]; then
    runtime_error "target node ID $target_id is virtual; choose a device-backed physical Audio/Sink"
  fi

  if [[ $node_policy_endpoint == true ]]; then
    runtime_error "target node ID $target_id is a virtual, fallback, null, or filter endpoint"
  fi

  if [[ -z $node_name ]]; then
    runtime_error "target node ID $target_id has no stable node.name and cannot be persisted safely"
  fi

  if looks_like_lua_number "$node_name"; then
    runtime_error "target node ID $target_id has numeric-looking node.name '$node_name', which WirePlumber would misread as an object serial"
  fi

  validate_unique_name_resolution "target" "$target_id"

  if [[ $node_name == funforgiven.audio.channel.* ]]; then
    runtime_error "target node ID $target_id uses the reserved internal channel name '$node_name'"
  fi

  device_id=$node_device_id
  if ! is_global_id "$device_id"; then
    runtime_error "target node ID $target_id is not device-backed; choose a physical Audio/Sink"
  fi

  if [[ $node_device_count != 1 ]]; then
    runtime_error "target node ID $target_id references device ID $device_id, but exactly one live PipeWire device was not found"
  fi

  if target_has_available_routes "$target_id" "$device_id"; then
    :
  else
    availability_status=$?
    if ((availability_status == 1)); then
      runtime_error "target node ID $target_id has no available hardware route"
    fi
    runtime_error "could not validate hardware route availability for target node ID $target_id"
  fi

  if target_would_create_cycle "$target_id" "$bridge_id" >/dev/null; then
    runtime_error "target node ID $target_id would create an audio graph cycle back to bridge node ID $bridge_id"
  else
    cycle_status=$?
    if ((cycle_status != 1)); then
      runtime_error "could not prove that target node ID $target_id is cycle-safe from the structured PipeWire link graph"
    fi
  fi

  hardware_target_name=$node_name
}

move_stream() {
  local source_id=$1
  local source_serial=$2
  local channel_id=$3
  local metadata_serial

  load_graph
  validate_source_stream "$source_id" "$source_serial"
  resolve_logical_sink "$channel_id"
  capture_default_metadata
  metadata_serial=$default_metadata_serial

  if ! pw-metadata -n default -- "$source_id" target.object "$destination_serial" Spa:Id; then
    runtime_error "failed to move source node ID $source_id to channel '$channel_id' (sink object.serial $destination_serial)"
  fi

  load_graph
  require_same_default_metadata "$metadata_serial"
  validate_source_stream "$source_id" "$source_serial"
  if ! target_metadata_is "$source_id" Spa:Id "$destination_serial"; then
    runtime_error "default metadata did not confirm target.object=$destination_serial (Spa:Id) for subject $source_id"
  fi
}

validate_bridge_snapshot() {
  local bridge_id=$1
  local bridge_serial=$2
  local target_id=$3
  local target_serial=$4

  validate_bridge "$bridge_id" "$bridge_serial" "$tx_channel"
  if [[ $tx_kind == move ]]; then
    validate_hardware_target "$bridge_id" "$target_id" "$target_serial"
  fi
}

# run_bridge_transaction move|reset BRIDGE_ID BRIDGE_SERIAL CHANNEL_ID
#   [TARGET_ID TARGET_SERIAL]
run_bridge_transaction() {
  local kind=$1
  local bridge_id=$2
  local bridge_serial=$3
  local channel_id=$4
  local target_id=${5-}
  local target_serial=${6-}
  local metadata_serial
  local nonce
  local request
  local requested_target_name

  tx_kind=$kind
  tx_channel=$channel_id
  acquire_channel_transaction_lock "$channel_id"
  load_graph
  validate_bridge_snapshot "$bridge_id" "$bridge_serial" "$target_id" "$target_serial"
  requested_target_name=$hardware_target_name
  capture_default_metadata
  metadata_serial=$default_metadata_serial

  nonce="${bridge_serial}:${BASHPID}:${RANDOM}:${RANDOM}"
  request=$nonce
  if [[ $kind == move ]]; then
    request="$nonce:$target_serial"
  fi
  prepare_transaction "$kind" "$bridge_id" "$nonce" "$request"
  if ! read_transaction_state; then
    runtime_error "could not inspect $tx_action controls for bridge subject $bridge_id"
  fi
  if [[ -n $tx_state_keys ]]; then
    runtime_error "default metadata still contains $tx_action controls ($tx_state_keys) for bridge subject $bridge_id"
  fi

  arm_transaction_cleanup
  if ! pw-metadata -n default -- \
    "$bridge_id" "$tx_request_key" "$request" Spa:String; then
    runtime_error "failed to arm the $tx_action for channel '$channel_id' bridge node ID $bridge_id"
  fi

  load_graph
  require_same_default_metadata "$metadata_serial"
  validate_bridge_snapshot "$bridge_id" "$bridge_serial" "$target_id" "$target_serial"
  await_transaction armed "$target_id" "$metadata_serial"

  case $kind in
    move)
      if ! pw-metadata -n default -- \
        "$bridge_id" target.object "$target_serial" Spa:Id; then
        fail_transaction "failed to move channel '$channel_id' bridge node ID $bridge_id to target node ID $target_id"
      fi
      ;;
    reset)
      if ! pw-metadata -n default -- \
        "$bridge_id" "$reset_commit_key" "$nonce" Spa:String; then
        fail_transaction "failed to commit the output reset for channel '$channel_id' bridge node ID $bridge_id"
      fi
      ;;
  esac
  await_transaction acknowledged "$target_id" "$metadata_serial"

  load_graph
  require_same_default_metadata "$metadata_serial"
  validate_bridge "$bridge_id" "$bridge_serial" "$channel_id"
  if [[ $kind == move ]] \
    && ! target_metadata_is "$bridge_id" Spa:String "$requested_target_name"; then
    fail_transaction "WirePlumber did not confirm the normalized durable target for bridge subject $bridge_id"
  fi

  finish_transaction
  require_same_default_metadata "$metadata_serial"
  release_channel_transaction_lock
}

main() {
  if (($# == 1)) && [[ $1 == "--help" ]]; then
    usage
    return 0
  fi

  if (($# == 0)); then
    usage_error "an action is required"
  fi

  case $1 in
    move-stream)
      (($# == 4)) || usage_error "move-stream requires SOURCE_ID SOURCE_SERIAL CHANNEL_ID"
      validate_global_id_argument "SOURCE_ID" "$2"
      validate_serial_argument "SOURCE_SERIAL" "$3"
      validate_channel_argument "$4"
      require_commands
      move_stream "$2" "$3" "$4"
      ;;
    move-bridge)
      (($# == 6)) || usage_error "move-bridge requires BRIDGE_ID BRIDGE_SERIAL CHANNEL_ID TARGET_ID TARGET_SERIAL"
      validate_global_id_argument "BRIDGE_ID" "$2"
      validate_serial_argument "BRIDGE_SERIAL" "$3"
      validate_channel_argument "$4"
      validate_global_id_argument "TARGET_ID" "$5"
      validate_serial_argument "TARGET_SERIAL" "$6"
      require_commands
      run_bridge_transaction move "$2" "$3" "$4" "$5" "$6"
      ;;
    forget-bridge-target)
      (($# == 4)) || usage_error "forget-bridge-target requires BRIDGE_ID BRIDGE_SERIAL CHANNEL_ID"
      validate_global_id_argument "BRIDGE_ID" "$2"
      validate_serial_argument "BRIDGE_SERIAL" "$3"
      validate_channel_argument "$4"
      require_commands
      run_bridge_transaction reset "$2" "$3" "$4"
      ;;
    --help)
      usage_error "--help does not accept additional arguments"
      ;;
    *)
      usage_error "unknown action '$1'; expected move-stream, move-bridge, or forget-bridge-target"
      ;;
  esac
}

if [[ ${BASH_SOURCE[0]} == "$0" ]]; then
  main "$@"
fi

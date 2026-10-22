# Sourced by audio-channels.nix after it declares `sink_names` (channel -> node.name).

program_name=${0##*/}

usage() {
  cat <<'EOF'
Usage:
  funforgiven-audioctl move-stream SOURCE_ID SOURCE_SERIAL CHANNEL_ID

Moves one application playback stream to a logical channel. WirePlumber saves
the route per application. SOURCE_ID and SOURCE_SERIAL must come from the
current PipeWire graph; a reused node ID with a different object.serial is
refused.
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

move_stream() {
  local source_id=$1 source_serial=$2 channel_id=$3
  local graph facts sink_serial

  graph=$(pw-dump) || runtime_error "pw-dump could not read the PipeWire graph"

  facts=$(jq -r --arg id "$source_id" --arg sink "${sink_names[$channel_id]}" '
    def nodes: .[] | select(.type == "PipeWire:Interface:Node");
    [nodes | select((.id | tostring) == $id) | .info.props] as $source
    | [nodes | select(.info.props["node.name"] == $sink) | .info.props["object.serial"] | tostring] as $sinks
    | [
        ($source | length),
        ($source[0]["object.serial"] // "" | tostring),
        ($source[0]["media.class"] // ""),
        ($source[0] // {} | has("funforgiven.audio.channel")),
        ($sinks | length),
        ($sinks[0] // "")
      ]
    | .[]
  ' <<<"$graph") || runtime_error "could not inspect the PipeWire graph"

  local count serial media_class internal sink_count
  { read -r count; read -r serial; read -r media_class; read -r internal; read -r sink_count; read -r sink_serial; } <<<"$facts"

  ((count == 1)) || runtime_error "source node ID $source_id is no longer live; refresh the mixer and try again"
  [[ $serial == "$source_serial" ]] ||
    runtime_error "source node ID $source_id is stale or was reused: expected object.serial $source_serial, found $serial"
  [[ $media_class == Stream/Output/Audio ]] ||
    runtime_error "source node ID $source_id is '$media_class', not a Stream/Output/Audio playback stream"
  [[ $internal == false ]] ||
    runtime_error "source node ID $source_id is an internal audio-channel node, not an application playback stream"
  ((sink_count == 1)) ||
    runtime_error "expected one live '$channel_id' channel sink, found $sink_count"

  pw-metadata -n default -- "$source_id" target.object "$sink_serial" Spa:Id >/dev/null ||
    runtime_error "failed to move source node ID $source_id to channel '$channel_id'"
}

main() {
  case ${1-} in
    --help)
      (($# == 1)) || usage_error "--help does not accept additional arguments"
      usage
      ;;
    move-stream)
      (($# == 4)) || usage_error "move-stream requires SOURCE_ID SOURCE_SERIAL CHANNEL_ID"
      [[ $2 =~ ^(0|[1-9][0-9]{0,9})$ ]] ||
        usage_error "SOURCE_ID must be a decimal PipeWire global ID without leading zeros; got '$2'"
      [[ $3 =~ ^(0|[1-9][0-9]{0,19})$ ]] ||
        usage_error "SOURCE_SERIAL must be a decimal PipeWire object.serial without leading zeros; got '$3'"
      [[ -n ${sink_names[$4]-} ]] ||
        usage_error "CHANNEL_ID must be exactly one of ${!sink_names[*]}; got '$4'"
      move_stream "$2" "$3" "$4"
      ;;
    "") usage_error "an action is required" ;;
    *) usage_error "unknown action '$1'; expected move-stream" ;;
  esac
}

main "$@"

# Audio channels

This component provides four logical playback channels—System, Game, Voice
Chat, and Music—on top of PipeWire and WirePlumber. Applications connect to a
logical sink; WirePlumber routes each channel bridge to one physical output.

## Behavior

- Every channel has one logical `Audio/Sink` and one bridge stream.
- New playback starts on System unless an application has saved routing state.
- Application routing and each channel's physical output survive a complete
  PipeWire/WirePlumber restart.
- Channel gain and mute apply to the bridge. Individual application streams
  remain independently controllable.
- A saved physical output is matched by stable node identity. If it disappears,
  the channel remains disconnected instead of silently choosing another output;
  reconnecting the same output restores the route.
- Forgetting one channel's saved output selects the deterministic first eligible
  physical sink for that channel only.
- Logical sinks are never accepted as physical targets, preventing feedback
  cycles.

WirePlumber owns routing persistence and bridge normalization. The command-line
helper requests a change and confirms it against the live graph; it does not keep
a second state database.

## Commands

Inspect the named graph before changing it:

```sh
wpctl status -n
pw-dump | jq '.[]
  | select(.type == "PipeWire:Interface:Node")
  | select(.info.props["funforgiven.audio.kind"] == "bridge")
  | { id, props: .info.props }'
```

Use `funforgiven-audioctl` for application and bridge routing. Commands that
refer to a live object require both its current PipeWire ID and `object.serial`;
this prevents an old UI action from targeting a newly reused numeric ID.

Forget one channel's saved physical target:

```sh
funforgiven-audioctl forget-bridge-target BRIDGE_ID BRIDGE_SERIAL system
```

Reset only that bridge's live gain and mute:

```sh
wpctl set-volume BRIDGE_ID 1.0
wpctl set-mute BRIDGE_ID 0
```

Inspect the dedicated persistence file while diagnosing a route, but do not edit
it while WirePlumber is running:

```sh
sed -n '1,120p' \
  "${XDG_STATE_HOME:-$HOME/.local/state}/wireplumber/funforgiven-channel-output-targets"
```

Do not use `wpctl reset --all` or remove unrelated WirePlumber device/profile
state as channel recovery.

## Validation

The repository checks parse the generated PipeWire configuration, compile the
WirePlumber policy, lint the helper, and exercise the complete graph in an
isolated PipeWire/WirePlumber runtime:

```sh
nix build \
  .#checks.x86_64-linux.audio-channels-pipewire-config \
  .#checks.x86_64-linux.audio-channels-wireplumber-lua \
  .#checks.x86_64-linux.audio-channels-audioctl \
  .#checks.x86_64-linux.audio-channels-integration \
  --no-link --accept-flake-config
```

After changing the deployed configuration, manually verify:

1. Playback from native PipeWire, Pulse-compatible, browser, voice-chat, and
   game clients appears under the intended application identity.
2. Streams move between all four channels and remain there after logout or
   reboot.
3. Each channel changes physical outputs and recovers after real hotplug.
4. Removing the selected output does not create a fallback route or cycle.
5. Gain, mute, latency, CPU use, and xruns remain acceptable with real playback.

PipeWire metadata has no compare-and-set operation combining an object ID and
expected serial. A small destroy/reuse window remains between the last graph
check and the metadata request; post-change confirmation reports the mismatch
but cannot undo a request already issued.

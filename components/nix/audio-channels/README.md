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

## RØDECaster Duo

The `rodecaster-duo` feature on `parmigiano` supports standard and expanded USB 1
playback. Standard mode (`19f7:0050`) uses Pro Audio to expose Main and Chat.
**Expanded mode uses a custom ALSA UCM HiFi profile** to expose System, Game,
Chat, and Music as separate stereo hardware outputs. PipeWire's native SplitPCM
support sends each stream to its own USB channel pair; no RØDE driver is needed
for this Linux setup.

The mixer, routing helper, and WirePlumber policy accept native ALSA SplitPCM
outputs as hardware destinations despite their internal loopback group. They
still require a device-backed output and exclude effect filters and logical
channel sinks.

Connect the computer to **USB 1** and set **Settings → Outputs → Multitrack →
USB 1 Input → Expanded** on the Duo. USB 1 Output can remain stereo for gaming
and calls; enable multitrack output only when individual recording tracks are
needed. Changing USB modes reconnects the audio device.

The four logical channels use these saved physical outputs. Quickshell shows
the destination as a read-only label and keeps application-to-channel routing;
channel volume and mute are controlled on the Duo. The channel output selectors,
software gain sliders, and mute buttons are omitted from the shell.

| Logical channel | PipeWire physical output | Duo fader assignment |
| --- | --- | --- |
| System | RØDECaster Duo System | USB 1 / System |
| Game | RØDECaster Duo Game | Game |
| Voice Chat | RØDECaster Duo Chat | USB 1 Chat |
| Music | RØDECaster Duo Music | Music |

Press the button above each physical fader, open its settings cog, and assign the
corresponding input. Using all four physical faders for computer audio means
microphones must use the Duo's on-screen virtual faders. WirePlumber remembers
each logical channel's physical output. To establish or change a route from the
terminal, find the bridge and physical sink IDs/serials with `pw-dump`, then use:

```sh
funforgiven-audioctl move-bridge BRIDGE_ID BRIDGE_SERIAL CHANNEL_ID TARGET_ID TARGET_SERIAL
```

In Expanded mode, PCM 1's playback pairs 1–2, 3–4, and 5–6 carry System, Game,
and Music respectively. Chat uses the separate stereo PCM 0. The profile exposes
only these four playback destinations; virtual A/B are unused. It matches the
expanded-mode USB IDs `19f7:0079` (stereo capture), `19f7:0073` (older 16-channel
capture), and `19f7:0095` (20-channel capture). The UCM package retains all other
distribution profiles and is selected only for the WirePlumber service.

Select **RØDECaster Duo Chat Capture** as the input in a communications app.
Configure the Duo's USB 1 Chat output mix/mix-minus to send the desired
microphones without returning the caller's audio to them. Main Capture is the
stereo main mix or full multitrack stream, depending on USB 1 Output settings.

The channel map is grounded in the
[Duo ALSA profile proposal](https://github.com/alsa-project/alsa-ucm-conf/pull/742)
and the [Linux Duo configuration](https://github.com/parzival-space/rodecaster-pro-2-virtual-devices-pipewire).
RØDE's [virtual-device guide](https://help.rode.com/hc/en-us/articles/17214867752847-Virtual-Devices)
documents the on-device Expanded setting and fader assignments.

For individual recording tracks, enable **USB 1 Output** multitrack under
**Settings → Outputs → Multitrack** on the Duo, then reconnect it and select
**Main Capture** in the recording application. The device determines the
available capture channels. Firmware 1.7.3 changed the layout to 20 channels:
the main mix on 1–2, then nine stereo fader pairs on 3–20. Older firmware uses a
different layout; consult RØDE's
[multitrack channel layout](https://help.rode.com/hc/en-us/articles/15412830674959-The-R%C3%98DECaster-Pro-II-Duo-Multitrack-Channel-Layout)
before assigning individual tracks. Multitrack capture does not add PC playback
destinations.

After rebuilding, restart WirePlumber to load the labels and channel maps:

```sh
sudo nixos-rebuild switch --flake path:.#parmigiano --accept-flake-config
systemctl --user restart wireplumber
wpctl status -n
```

An existing saved profile takes precedence over the rule's default. Find the
Duo's current device ID in `wpctl status -n`, inspect
`pw-cli enum-params DEVICE_ID EnumProfile`, then select the index named **HiFi**
for Expanded mode using `wpctl set-profile DEVICE_ID PROFILE_INDEX`. Pro Audio
exposes raw multichannel ports and does not provide the four split outputs.
Standard mode instead uses `pro-audio`. Do not reuse numeric IDs from an earlier
session.

Changing USB modes or profiles replaces the node names. Update all four saved
physical targets with `move-bridge` and re-select the communications app's input.
Existing routes intentionally stay disconnected until their new destination is
selected. For verification, play one channel at a time and check that only its
assigned fader controls it, including mute, then verify the routes after a
WirePlumber restart and USB reconnect.

## Duo MIDI routing pads

The desktop service `funforgiven-audio-midi` routes the focused Niri
application's active playback to one of the four channels. On the Duo, enable
MIDI under **Settings → System → MIDI**, then configure four SMART pads as
**MIDI → Custom → Control Change**, using **channel 16**, **value 127**, and
**On only**:

| Pad label | CC number | Destination |
| --- | --- | --- |
| System | 102 | System |
| Game | 103 | Game |
| Voice | 104 | Voice Chat |
| Music | 105 | Music |

These controls are separate from the Duo's default fader and button MIDI
messages. See RØDE's [MIDI trigger instructions](https://help.rode.com/hc/en-us/articles/8565481010063-MIDI-Triggers-for-R%C3%98DECaster-Pro-II-Duo)
for editing a pad. The service opens only the Duo's named MIDI input, reconnects
when the device returns, and starts with the graphical session.

Focus an application that is playing audio, then press a pad. A notification
confirms the destination. The app is captured when the MIDI message arrives;
changing focus while a previous move finishes cannot change the captured app.
All matching playback streams move together. Browsers are treated as one app,
so this can include several tabs or windows. Applications without an active
playback stream need to start audio before they can be moved. WirePlumber saves
the route using its existing application stream identity; MIDI routing does not
change the default sink or any volume settings.

Inspect matching streams without moving them, or route the focused app manually:

```sh
funforgiven-audio-midi route game --dry-run
funforgiven-audio-midi route game
systemctl --user status funforgiven-audio-midi
journalctl --user -u funforgiven-audio-midi -b
```

The terminal is the focused app when commands are entered there. For manual
testing, delay the command long enough to focus the intended app first:

```sh
sleep 3; funforgiven-audio-midi route game --dry-run
```

## Validation

The repository checks parse the generated PipeWire configuration, compile the
WirePlumber policy, lint the helper, and exercise the complete graph in an
isolated PipeWire/WirePlumber runtime:

```sh
nix build \
  .#checks.x86_64-linux.rodecaster-duo-ucm \
  .#checks.x86_64-linux.audio-channels-pipewire-config \
  .#checks.x86_64-linux.audio-channels-wireplumber-lua \
  .#checks.x86_64-linux.audio-channels-audioctl \
  .#checks.x86_64-linux.audio-channels-integration \
  .#checks.x86_64-linux.audio-midi \
  --no-link --accept-flake-config
```

The Duo check parses the built profiles with ALSA's native UCM library and checks
the independent playback channel pairs and 2/16/20-channel capture modes without
opening audio hardware.

The MIDI check covers focus capture, process and application matching, stale
PIDs, internal-stream exclusions, controller filtering, and invocation of the
existing routing helper. Pad programming and physical MIDI delivery require a
connected Duo for verification.

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

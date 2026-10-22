# Audio channels

Four logical playback channels (System, Game, Voice Chat, Music). Each is a
virtual sink plus a loopback "bridge" that plays into one fixed [RØDECaster Duo](../rodecaster-duo/README.md)
output (`audio-channels.nix`), so every channel has its own hardware fader.
Applications pick a channel; the channel never picks a device.

- New playback goes to System (highest `priority.session`) unless WirePlumber
  has a saved route for the application. Moving a stream (Quickshell drag, Duo
  MIDI pad, `funforgiven-audioctl move-stream`) sets its `target.object`, which
  WirePlumber's stock stream-state saves per application.
- A bridge never falls back to another output (`node.dont-fallback`,
  `node.linger`): while the Duo is absent or in Standard mode the bridges stay
  unlinked, and they relink when the named output returns. Falling back could
  send a channel into another logical sink and create a feedback loop.
- Bridges ignore saved WirePlumber targets (`state.restore-target = false`), so
  the Nix-declared output always wins.
- The bridge targets embed the Duo's serial (`IR0076094`). A replacement Duo, or
  a different USB mode/profile, changes the node names: check
  `wpctl status -n` and update `duo` in `audio-channels.nix`.
- WirePlumber's default `node.restore-default-targets` must stay enabled; it
  persists the microphone chosen in Quickshell. The saved default sink should
  be the System channel.

`funforgiven-audioctl move-stream ID SERIAL CHANNEL` is the contract used by
Quickshell (`funforgiven/window-manager/quickshell/services/AudioActions.qml`) and the
[Duo pads](../duo-midi/README.md) (`duo-midi/audio.py`): it refuses a
reused ID whose `object.serial` changed, exits 64 on usage errors and 1 on
runtime errors, and prints errors on stderr. Callers confirm the move from the
live graph.

Do not use `wpctl reset --all` or delete unrelated WirePlumber state to recover
a route. The `audio-channels` check runs the generated configuration in an
isolated PipeWire/WirePlumber session.


# OBSBOT Tiny 3 controls

The camera icon beside the Quickshell audio button opens the Tiny 3 popup.
It offers sleep/wake, tracking on/off, three-degree PTZ arrows, center reset,
zoom, HDR, and the image controls exposed by the camera: exposure, white
balance, focus, brightness, contrast, saturation, sharpness and anti-flicker.
Turn off the corresponding auto control before adjusting its manual value.
Exposure time is displayed in milliseconds, using the kernel's
[documented 100 µs control units](https://docs.kernel.org/userspace-api/media/v4l/ext-ctrls-camera.html#v4l2-cid-exposure-absolute).

Framing, Exposure, Color and Focus each have a separate tab. Camera sliders
change only by clicking, dragging, or using the keyboard; wheel events scroll
the panel without changing settings.

Frame the camera with tracking off, then use the **save icon** beside Normal
call, Close-up or Standing. Each preset saves the live motor position,
zoom and image profile. Recalling it turns tracking off and restores those
values. The presets start empty because framing depends on the desk and room.

Image adjustments save automatically in
`${XDG_STATE_HOME:-~/.local/state}/obsbot/profiles.json`. Writes are atomic and
the file is private to the user. Confirmed image settings return on reconnect
or wake. Starting the shell does not wake or reposition a sleeping camera.
Corrupt profiles are reported and preserved.

On connection and during polling, the helper disables all seven voice command
bits, the USB microphone, and microphone operation during sleep. It verifies
the camera's readback. The NixOS module also disables the camera's ALSA device
in WirePlumber as a fallback. Disabling USB audio can make the device reconnect;
the helper discovers the matching capture node again. This does not establish
whether the internal microphone ADC is powered down; it disables USB audio
and voice command actions.

Tracking speed is currently unavailable: the Tiny 2 Standard/Sport command
(`0x0cc4`), the SDK's track-speed command (`0x0944`), and the legacy framing
did not change the Tiny 3's speed readback. The popup omits this control.

The transport is restricted to USB `3564:ff02` (PW106) with the expected vendor
extension GUID. It uses standard V4L2 controls and UVC extension queries through
the capture node; it does not run a vendor SDK, open a video stream, detach a
driver, or require raw USB access. The usual `video` group is sufficient.
Vendor frames follow the MIT-licensed
[obsbot-mcp protocol reference](https://github.com/lxman/obsbot-mcp/tree/ec9304b2722745d698db2632eddeacdf24da37cc/src/codec).
Voice/audio tags and motor-state decoding were checked against OBSBOT's SDK
disassembly. Linux's cached pan/tilt values are not used to save presets.

For troubleshooting, stop the shell before using the standalone CLI; the
helper holds an exclusive lock to prevent interleaved vendor replies:

```sh
obsbot-control status
obsbot-control wake
obsbot-control request '{"action":"hdr","value":true}'
obsbot-control sleep
```

Run the protocol, privacy, persistence and preset tests without a camera:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s components/nix/obsbot -v
nix build .#checks.x86_64-linux.obsbot-controller --no-link
```

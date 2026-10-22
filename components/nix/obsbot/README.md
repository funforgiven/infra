# OBSBOT Tiny 3 controls

`obsbot-control` drives the Tiny 3 (USB `3564:ff02`) for Quickshell's camera
popup using standard V4L2 controls and UVC extension queries on the capture
node: no vendor SDK, video stream, driver detach or raw USB access, so the
`video` group suffices. Vendor framing follows the MIT-licensed
[obsbot-mcp](https://github.com/lxman/obsbot-mcp/tree/ec9304b2722745d698db2632eddeacdf24da37cc/src/codec)
(see `NOTICE`); voice/audio tags and motor-state decoding were checked against
OBSBOT's SDK.

- **Privacy.** On connect and while polling, the helper disables voice commands,
  the USB microphone and microphone-during-sleep, and verifies the readback;
  WirePlumber also disables the camera's ALSA device. This does not prove the
  microphone ADC is powered down. Disabling USB audio can make the camera
  reconnect.
- **Presets** save the live motor position (not Linux's cached pan/tilt), zoom
  and image profile; image settings persist in
  `$XDG_STATE_HOME/obsbot/profiles.json` and are reapplied on reconnect or wake.
- **Tracking speed** is not offered: neither the Tiny 2 (`0x0cc4`) nor the SDK
  (`0x0944`) command changes the Tiny 3's readback.

The helper holds an exclusive lock, so stop the shell before using the CLI
(`obsbot-control status|wake|sleep`, or `request '{"action":"hdr","value":true}'`).

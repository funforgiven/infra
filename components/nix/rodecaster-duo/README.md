# RØDECaster Duo

Connect the PC to **USB 1** and set **Settings → Outputs → Multitrack → USB 1
Input → Expanded**. Expanded mode (USB IDs `19f7:0073/0079/0095`, by capture
width 16/2/20) uses the custom UCM HiFi profile in `Expanded.conf`: PCM 1
playback pairs 1–2, 3–4 and 5–6 carry System, Game and Music, and PCM 0 carries
Chat. PipeWire's SplitPCM turns them into four stereo sinks; no RØDE driver is
needed. Standard mode (`19f7:0050`) uses Pro Audio and exposes only Main and
Chat, which the [audio channels](../audio-channels/README.md) do not target.
The custom UCM tree is given only to WirePlumber; the `rodecaster-duo-ucm`
check parses it with ALSA's own UCM library.

Assign the four physical faders (button above the fader → settings cog) to
USB 1/System, Game, USB 1 Chat and Music. Microphones then use on-screen virtual
faders. A previously saved device profile overrides the rule's default: select
**HiFi** with `pw-cli enum-params DEVICE_ID EnumProfile` and
`wpctl set-profile DEVICE_ID INDEX` (IDs change every session).

**Call feed.** Select **RØDECaster Duo Chat Capture** in the call app. Under
Settings → Outputs → Routing → USB 1 Chat choose **Custom** and include only
Mic 1 and SMART pads. Mix-minus does not isolate the microphone: it removes only
the Chat return, so System, Game and Music would still reach callers. Verify by
speaking, playing an audio pad, and playing each PC channel separately.

**Multitrack.** Enable USB 1 Output multitrack and record from **Main Capture**.
Firmware 1.7.3+ uses 20 channels: main mix on 1–2, then nine stereo fader pairs.
See RØDE's [channel layout](https://help.rode.com/hc/en-us/articles/15412830674959-The-R%C3%98DECaster-Pro-II-Duo-Multitrack-Channel-Layout).

**HID buttons.** On firmware 1.7.6 the physical buttons stopped responding
after a USB HID client (e.g. a pad editor) read state and closed. The kernel
parameter `usbhid.quirks=0x19f7:0x0079:0x00000400` (HID_QUIRK_ALWAYS_POLL, only
for that USB ID) keeps the endpoint polled; it needs a PC reboot. Before a HID
session, confirm it in `/sys/module/usbhid/parameters/quirks`, and afterwards
test pads, bank arrows and mute buttons for several minutes with no reader open.

Sources: [UCM proposal](https://github.com/alsa-project/alsa-ucm-conf/pull/742),
[Linux Duo setup](https://github.com/parzival-space/rodecaster-pro-2-virtual-devices-pipewire),
[custom routing](https://help.rode.com/hc/en-us/articles/9011992585743-Why-Custom-Routing-in-Submixes-is-Essential-for-R%C3%98DECaster-Pro-II-and-R%C3%98DECaster-Duo).

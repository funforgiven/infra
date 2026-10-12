# Console access during migration

The proposed console setup is one PiKVM V4 Plus and one official PiKVM Switch,
with HDMI and USB connected to pecorino, taleggio and asiago. ATX connections
are intentionally absent. This is sufficient for remote video, keyboard,
mouse, boot-menu interaction and virtual installer media, provided each host's
firmware recognizes the emulated USB devices. It does not provide remote power
buttons or a guaranteed recovery path for a powered-off or frozen host.

No PiKVM port, input event, firmware setting, media attachment or server has
been changed during preparation. The new hardware has not been qualified.

## Existing device qualified on 12 October 2026

The registered ricotta device at `10.21.90.3` is a PiKVM v2 on Raspberry Pi 4,
not the proposed V4 Plus/switch combination. Its API has no switch endpoint.
The connected host is pecorino, identified by its source console messages and
a unique marker written to `/dev/tty0` over the independently pinned source SSH
session. The fresh captured console showed that exact marker and host name.

The supplied SSH key works for `funforgiven`. API authentication also uses
`funforgiven`; credentials remain in ignored mode-0600 files. Root inspection
used the second owner-provided password candidate. Nginx exposes HTTP locally,
so workstation access uses an encrypted SSH tunnel without changing device auth.
A WebSocket session keeps the streamer active while capturing fresh snapshots.

The USB controller is configured and virtual media is available. A harmless
Shift press/release returned HTTP 200 and changed keyboard status to online.
Mouse control, ISO attachment and firmware/media boot remain unqualified. The
old Ubuntu image stays detached. No power, boot or persistent PiKVM settings
were changed. The steps below for a switch apply only when one is connected;
taleggio and asiago have no qualified console path through this device yet.

## Operator and owner responsibilities

The owner connects the devices and supplies a reachable PiKVM address and
authenticated access through the existing credential mechanism. Keep the
PiKVM powered and accessible independently of all three servers. The access
path must survive stopping their Kubernetes, identity, DNS and VPN services;
test it from the workstation before the outage. Existing ricotta addressing
on the out-of-band network can be retained if the replacement uses that same
network. Do not depend on a VPN or login service hosted by the retiring cluster.

The remote operator can inspect screenshots, switch the active console, enter
UEFI or a boot menu, type installer commands, mount an ISO, install NixOS and
continue through SSH once networking works. For normal reboots, use the OS or
installer reboot command. The owner must press a physical power/reset button
if a machine is off or has stopped accepting console and OS commands. A
Ctrl-Alt-Delete shortcut only helps when firmware or the OS still handles it.
Wake-on-LAN may be qualified separately; it is not assumed as a recovery path.

## Qualification before installation

1. Record the physical host-to-switch-port mapping. The API uses zero-based
   continuous port numbers; the web interface labels the first switch's ports
   1.1 through 1.4. Verify the mapping against actual host identity before
   disk operations. Do not infer it solely from cable order or port names.
2. Authenticate and read `/api/info`, `/api/switch`, `/api/hid` and `/api/msd`.
   Credentials must not appear in command arguments, terminal output or Git.
   Use HTTPS with the device CA/certificate trusted by the workstation, or an
   SSH tunnel that protects access when the local endpoint is HTTP.
3. Select each port deliberately using `POST /api/switch/set_active?port=N`.
   Wait for the switch and USB devices to settle, then obtain a fresh image
   from `GET /api/streamer/snapshot`. Inspect it through the image-viewing
   tool; a live browser automation tool is not required.
4. In a harmless shell or firmware screen, qualify keys and typing. The API
   exposes `/api/hid/events/send_key`, `/api/hid/events/send_shortcut` and
   `/api/hid/print`. Match the host's keyboard layout, use short commands and
   inspect the screen after input. Release pressed keys on interruption.
5. Upload the reviewed installer ISO through `/api/msd/write`, choose it with
   `/api/msd/set_params` and attach it with `/api/msd/set_connected`. Verify
   the ISO checksum and that each host can boot its virtual media. A successful
   upload alone does not qualify a particular motherboard's boot support.
6. Keep the switch on a host while it needs virtual media. Changing ports
   moves its USB connection as well as video. Before moving away, finish
   installation or explicitly prove that the live environment and all
   required files are in RAM and no longer depend on the virtual drive.
7. After NixOS boots, qualify SSH, management networking and console login.
   Use SSH for file transfer and installation automation; retain PiKVM for
   boot failures and recovery. Console operations remain sequential across
   the three hosts; established SSH sessions can operate independently.

Hardware qualification belongs in the future live cutover. Backup verification,
disk identity checks and installation authorization remain prerequisites for
the destructive installation steps in the migration runbook. No autonomous
power recovery is claimed for this wiring.

## Primary references

- [PiKVM Switch wiring and operation](https://docs.pikvm.org/switch/)
- [PiKVM HTTP API](https://docs.pikvm.org/api/)
- [Virtual media and firmware compatibility](https://docs.pikvm.org/msd/)

Migration preparation and offline validation are complete; see
[ACCEPTANCE.md](ACCEPTANCE.md). This console plan does not qualify the actual
hardware, establish PiKVM connectivity or authorize live installation.

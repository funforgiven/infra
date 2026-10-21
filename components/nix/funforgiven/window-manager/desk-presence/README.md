# Desk presence and the AMOLED saver

## Current behavior

Desk-presence screen control is disabled in `../idle.nix`
(`deskPresenceEnabled = false`) because the sensor reported presence at an
empty desk. The screen saver activates after **120 seconds of input
inactivity** and wakes on keyboard, pointer or touch input. The presence reader
is not installed or started.

The FP300 is still used in Home Assistant for presence and climate data, with
Medium sensitivity, 2 m range, interference identification on and adaptive
sensitivity off.

## Optional presence mode (disabled)

When enabled in `../idle.nix`, Parmigiano uses the desk FP300's
`binary_sensor.0x54ef4410017220eb_presence` through Home Assistant's TLS
WebSocket API. The `desk-presence.service` user service only reads states;
it sends no Home Assistant service commands.

- Presence keeps all screens awake, including while reading without input.
- A clear desk activates Quickshell's black overlay. The sensor
  uses medium sensitivity and waits 30 seconds before reporting absence;
  Quickshell follows that report directly.
- Returning clears the overlay. Keyboard, pointer and touch input also wake
  it, allowing 30 seconds for the presence sensor to catch up.
- If HA disconnects or the entity becomes unavailable, the ordinary
  120-second input-idle timer takes over. A 45-second lease also expires
  stale presence if the reader crashes. The reader subscribes to the one
  entity, publishes changes immediately and, while the 10-second HA heartbeat
  is healthy, renews the lease every 25 seconds, which also resynchronizes
  Quickshell after it restarts.

The one-second swayidle timeout only listens for input resume; it does not
blank the display. The 120-second timeout tracks the input-idle state.
Niri's cursor still hides after 30 seconds. This is a screensaver, not a
session lock or a way to unlock a locked session.

## Credential and recovery

The local-only **Parmigiano desk presence** HA user belongs to the built-in
`system-read-only` group. Its long-lived token and recovery login are SOPS
encrypted in `secrets/home-assistant-presence.yaml`. Only the token is
deployed, as user-owned mode `0400`
`/run/secrets/home-assistant-presence-token`; systemd passes it using
`LoadCredential`. No plaintext token is embedded in the Nix store or command
line. The reader requires normal TLS certificate validation.

To restore presence mode, enable it in `../idle.nix` and apply the
NixOS configuration to install the user service.
The service starts after `graphical-session.target` and Quickshell, and
reconnects after HA or network interruptions. The session ordering
prevents a startup cycle that otherwise causes systemd to skip the reader at
login and leave the screen saver using its input-idle fallback. After
rotating the token, rebuild and restart `desk-presence.service` to refresh
systemd's credential copy.

```sh
systemctl --user status desk-presence swayidle
journalctl --user -u desk-presence -n 30
qs -c funforgiven-shell ipc call amoled status
systemd-analyze --user verify --man=no ~/.config/systemd/user/desk-presence.service
```

When presence mode is configured, temporarily stopping `desk-presence.service`
clears the presence override; starting it restores sensor control.

Tests cover occupied reading, absence before the idle timeout, input wake,
unavailable data, lease expiry, initial state, event updates and reconnect
cleanup:

```sh
nix build .#checks.x86_64-linux.desk-presence-reader \
  .#checks.x86_64-linux.quickshell-qml-interactions \
  .#checks.x86_64-linux.funforgiven-shell-qml
```

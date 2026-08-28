# Quickshell desktop shell

This directory contains the repository-owned Niri shell: per-output bars,
workspace and window controls, tray menus, a dock and launcher, the audio mixer,
session actions, and the black idle overlay.

Quickshell runs as a UWSM graphical-session service. Application launches go
through `uwsm-app`, and Niri remains the source of workspace, window, focus, and
output state. PipeWire and WirePlumber remain the source of audio state.

## Automated checks

The flake checks cover QML loading, JavaScript reducers, tray and popup
coordination, launcher commands, device-list interaction, theme contrast, Niri
state handling, and the patched Quickshell package.

Build the shell checks and the complete desktop before activation:

```sh
nix build \
  .#checks.x86_64-linux.funforgiven-shell-qml \
  .#checks.x86_64-linux.quickshell-qml-interactions \
  .#checks.x86_64-linux.quickshell-niri-state \
  .#checks.x86_64-linux.quickshell-runtime-contracts \
  .#checks.x86_64-linux.quickshell-runtime-smoke \
  .#checks.x86_64-linux.quickshell-desktop-entries \
  .#checks.x86_64-linux.quickshell-theme-contrast \
  .#checks.x86_64-linux.parmigiano-home \
  .#checks.x86_64-linux.parmigiano-toplevel \
  --no-link --accept-flake-config
```

Automated checks do not replace interaction testing in the real Niri session.

## Activate a change

Apply the NixOS configuration, then log out and back in. A rebuild cannot replace
the compositor or UWSM session serving the current login.

```sh
sudo nixos-rebuild switch --flake .#parmigiano --accept-flake-config
```

After login, inspect the shell service and its current-boot journal:

```sh
systemctl --user status quickshell.service
journalctl --user -b -u quickshell.service
```

There should be one Quickshell process in `session-graphical.slice`, with no
remaining DankMaterialShell process, unit, startup entry, or environment hook.

## Manual test checklist

### Outputs, workspaces, and tray

1. Confirm every output has one bar and the expected output-local workspaces.
2. Focus, move, add, and remove windows; workspace counts and application icons
   must update without recreating unrelated items.
3. Open short and long tray menus. Switch rapidly between several applications,
   use submenus, scroll, activate an item, press Escape, click outside in every
   direction, and close the owning application. Only one popup may remain open.
4. Hotplug an output with a popup open and confirm the popup moves or closes
   without leaving an input-blocking surface.

### Dock and launcher

1. Launch and focus applications on every output. Focusing a window must not
   move the pointer away from the dock.
2. Confirm successful launches do not flash unrelated dock tiles and that the
   nine-dot launcher control does not mirror application start state.
3. Start a harmless application and confirm its UWSM unit is in
   `app-graphical.slice`, inherits the display/Niri/Qt/XDG environment, and has
   `KillMode=mixed`.
4. Launch a deliberately invalid desktop entry and confirm the failure is shown
   on the originating item.
5. Restart Quickshell while an application is running; the application must
   remain alive.
6. Exercise the launcher from every output with an empty query, a no-match query,
   keyboard and pointer selection, a pending start, and a failed start. It must
   stay on the configured primary output and take keyboard focus immediately.

### Mixer

1. Open, dismiss, and reopen the mixer during rapid stream creation and removal.
2. Move individual and grouped streams in both directions, cancel drags, and
   confirm a pending move does not briefly create an Unrouted item.
3. Use keyboard routing and pointer routing; both must wait for the same
   PipeWire graph confirmation.
4. Scroll an output or microphone list and immediately click the visible row at
   the same pointer coordinate. The newly visible row must activate once; a real
   drag or flick must activate nothing.
5. Switch real hardware outputs, restart PipeWire/WirePlumber, and verify saved
   stream and bridge routes return without a feedback cycle.

### Idle overlay and session lifecycle

1. Exercise the black overlay on every output, over fullscreen content, after
   hotplug, and with variable refresh enabled.
2. Wake it with pointer, keyboard, and touch input. The first wake event must
   reach the session, and no shell strip may remain visible over the black
   surface.
3. Restart Quickshell while idle and confirm the overlay returns to the correct
   state without changing display modes.
4. With several Firefox tabs open, log out through the shell, log back in, and
   confirm Firefox restores without its crash-recovery page. The application
   service must stop before Niri and receive its normal graceful shutdown window.
5. Reboot and test the previous NixOS generation before deleting old desktop
   state.

### Input methods

Verify the Fcitx tray item switches only between Turkish direct input and Mozc,
Hiragana and Katakana conversion work, and `Ctrl+Space` still reaches games that
use it. Test Firefox, a Qt text field, a terminal, and at least one game.

## Polkit

The native Quickshell authentication agent is optional and is not part of the
ordinary shell interaction checklist. Keep the KDE agent selected unless the
dedicated [polkit validation](polkit/README.md) passes in one deployed session.

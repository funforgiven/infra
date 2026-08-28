# Quickshell polkit agent

The host currently selects the KDE polkit agent. The Quickshell agent is an
optional alternative selected with:

```nix
dendritic.polkit.agent = "quickshell";
```

The selector also disables the KDE `niri-flake-polkit` unit and enables the
native Quickshell UI. Change it only for a dedicated test generation, then log
out and back in so the old listener stops before the new one registers.

Before changing the deployed host, build the alternate Home Manager and NixOS
configurations and start the shell in a headless Weston session:

```sh
nix build \
  .#checks.x86_64-linux.quickshell-native-polkit-home \
  .#checks.x86_64-linux.quickshell-native-polkit-toplevel \
  .#checks.x86_64-linux.quickshell-native-polkit-smoke \
  --no-link --accept-flake-config
```

## Security properties

The dialog accepts only Unix-user identities supported by the pinned Quickshell
backend. Authentication responses are cleared and the editor is destroyed after
submit, cancel, failure, completion, or identity change. Copy, cut, undo, and
redo shortcuts are consumed, and the response is not sent to logging,
persistence, or clipboard APIs.

This is not a secure-memory-erasure guarantee. Qt, Quickshell, PAM, and temporary
buffers may retain copies until normal destruction.

Only an active authentication flow requests exclusive keyboard focus. A
registration warning does not take keyboard focus. The overlay follows Niri's
focused output and falls back to a connected output if hotplug temporarily makes
focus information incomplete.

## Required interactive test

Run every item after selecting the Quickshell agent and starting a fresh login
session:

1. Run `pkexec` with a correct password and then an incorrect password.
2. Retry after failure and cancel using both the button and Escape.
3. Complete a PAM flow that displays an informational or visible-response
   prompt.
4. Trigger a request that permits multiple identities and switch identities
   before and during the prompt.
5. Test multi-turn PAM, fingerprint, or 2FA when configured, including
   informational and error messages.
6. Start two concurrent `pkexec` requests. One dialog must process them in FIFO
   order without exposing the previous response.
7. Focus every monitor, including over a fullscreen window, and confirm the one
   overlay follows Niri's focused output.
8. Reload Quickshell during a request, then kill it during a request. systemd
   must restart it, and the caller must be cancelled or able to retry cleanly.
9. Confirm `niri-flake-polkit.service` is disabled and no KDE authentication
   agent process remains.
10. Log out and back in again and confirm registration succeeds exactly once.

Inspect the service and journal directly:

```sh
systemctl --user status quickshell.service niri-flake-polkit.service
journalctl --user -b -u quickshell.service -u niri-flake-polkit.service
```

Polkit does not provide a public API that enumerates every registered
authentication agent. Process and unit inspection therefore cannot prove that
an arbitrary third-party listener is absent.

## Backend limits

The pinned Quickshell backend exposes registration state but not a registration
error or retry API. If registration remains false, recovery requires restarting
`quickshell.service` and inspecting its journal. A crashed shell cannot display
its own failure until systemd restarts it.

Queueing is internal to Quickshell, and queue depth is not exposed to QML. The
local backend patch is tied to the pinned Quickshell version and must be reviewed
again on upgrade. Keep KDE selected until concurrent requests, cancellation,
reload, crash/restart, registration, and exactly-one-agent tests pass together
in the same deployed generation.

# Valheim 1.0

One vanilla Valheim server (Steam backend) runs in `games` as a single writer.
Public listing plus a shared password; no initial administrators. Crossplay
would need the launch arguments and readiness check changed together: PlayFab
supports neither LAN-IP connections nor the Steam A2S query `ready.py` uses.

## Why it is built this way

- **The game is not version-pinned.** The image digest pins only the community
  container tooling. Every pod start reinstalls Steam app `896660` from the
  `public` branch into an ephemeral volume, so a reschedule can update the
  server; clients must match it. Only `/data` (worlds, permission lists, Steam
  home) is persistent and backed up.
- **World upgrades are one-way.** Changing the image digest rolls back neither
  the Steam install nor a migrated world. Take a completed backup before
  anything that may update the game.
- **PlayFab needs a passwd entry.** The bundled PlayFab library calls
  `getpwuid(getuid())` even with the Steam backend, so `prepare-identity.sh`
  writes `/etc/passwd`/`/etc/group` with a UID 1000 `valheim` account onto an
  ephemeral volume that the game mounts read-only.
- Supervisor (`supervisord.conf`) turns pod termination into the SIGINT that
  makes Valheim save before exiting; its control socket has no network listener.

## Credentials

`VALHEIM_GAME_PASSWORD` (12–128 characters, not contained in the server name)
is enrolled with `nix run .#enroll-services-credential -- VALHEIM_GAME_PASSWORD`
and rendered by `nix run .#render-cluster-credentials` into `valheim-runtime`.
It is read when the game process starts; restart the pod to apply a rotation.
WAN forwards are reconciled by the RouterOS playbook (`--tags wan-port-forwards`).

## Backup and recovery

`/data` is in the daily volume snapshots ([backups](../../infrastructure/backups/README.md));
Valheim's own rotating world backups (`-backups 12`) live beside the world, so a
snapshot taken mid-save still holds a loadable copy. To recover, restore the
volume with the StatefulSet stopped, fall back to the newest backup copy only if
the world fails to load, and check it with a real player.

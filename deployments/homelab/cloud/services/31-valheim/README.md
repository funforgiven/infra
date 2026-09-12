# Valheim 1.0

One vanilla Valheim server runs in the `games` namespace of `services-v1`,
following Factorio's Flux, Cinder, RouterOS, SOPS, monitoring, and Velero setup.

| Surface | Value |
| --- | --- |
| Server browser name | `Fahrican Valheim` |
| World | `Fahrican`, new world with normal vanilla settings |
| Clients | Steam, including Steam Deck; up to 10 players |
| Provider VIP | `10.21.40.124:2456/udp`; Steam query port `2457/udp` |
| Internet path | CCR2004 WAN UDP `2456-2457` to the provider VIP, with LAN reflection |
| State | One retained 20 GiB `rbd1` volume; one writer |
| Runtime | 2 CPU and 4 GiB requested; 8 GiB memory ceiling; no CPU throttle |
| Access | Public listing, separate shared password; no initial administrators |
| Saves | Every 10 minutes, plus 12 built-in backups |

Friends use the public browser or the site's public IP on port `2456`. Steam
Favorites uses query port `2457`. The trusted LAN can connect directly to
`10.21.40.124:2456`; other local LANs use the public endpoint through reflection.
The Supervisor control socket is local to the container and has no network
listener. Only the two game UDP ports are exposed.

The deployment currently uses the Steam backend. Crossplay requires changing
the launch arguments and readiness check together: PlayFab does not support
LAN-IP connections or Steam A2S queries. See Iron Gate's
[dedicated server guide](https://www.valheimgame.com/support/a-guide-to-dedicated-servers/).

## Runtime and updates

The [community runtime image](https://github.com/community-valheim-tools/valheim-server-docker)
is pinned by digest (image version 1.2.0, source commit
`a134fb4dc7a850eec5b3ba7f0bc89bce434f0348`). This version number belongs to the
container tooling, not to the game. The init container installs Steam app
`896660` from the `public` branch, which supplies the current stable game.
The readiness check requires a reported `1.0.x` version.

The game binaries are **not version-pinned**: every pod initialization checks
Steam for a stable update, including after rescheduling. A child-process restart
or backup does not run SteamCMD. There is no periodic update job. Clients must
match the installed server version; inspect the startup logs after an update.

The repository's scripts replace the image's root bootstrap with a Supervisor
running as UID/GID 1000, a read-only root filesystem, and no Linux capabilities.
The installer prepares account files on an ephemeral volume and the game mounts
them read-only at `/etc/passwd` and `/etc/group`. This gives UID 1000 a real
`valheim` account with `/data/home` as its home directory; the bundled PlayFab
library requires this lookup even when the server uses the Steam backend.
SteamCMD, its home directory, and the installed server are writable on the PVC.
`/data/worlds` contains saves and permission lists. Do not delete the PVC to
repair an installation; game binaries live separately at `/data/server`.

## Credentials and activation

`VALHEIM_GAME_PASSWORD` is enrolled in the services runtime SOPS document. The
services-cluster reconciler delivers it as `games/valheim-runtime`. No Steam
account or service token is required for the anonymous dedicated-server download.
Retrieve the game password privately with an authenticated services-cluster
session and retain it in your password manager:

```sh
kubectl -n games get secret valheim-runtime \
  -o jsonpath='{.data.VALHEIM_GAME_PASSWORD}' | base64 --decode
```

To rotate it using the existing hidden-input enrollment tool:

```sh
nix run .#enroll-services-credential -- VALHEIM_GAME_PASSWORD
```

Use 12–128 characters, no newlines, and a value absent from the server name.
After committing the desired state and reconciling the services runtime,
Flux deploys `services-valheim`. Apply the declared network surface:

```sh
cd components/cloud/network-automation
ansible-playbook reconcile-routeros.yaml \
  --limit core_router --tags wan-port-forwards
```

This reconciles all declared game and Syncthing forwards. Wait for the Valheim
StatefulSet and `10.21.40.124` LoadBalancer address, then verify one LAN and one
external player connection. Initial Steam downloads can take several minutes.
The two game servers together request 4 CPU and 8 GiB before platform overhead;
check worker capacity before activation. Password changes are picked up at the
next game-process start; schedule a restart after secret reconciliation when
immediate rotation is needed.

## Backup and recovery

The existing daily (30-day retention) and weekly (90-day retention) Velero
schedules include `games`. Before copying the PVC, `backup.sh` asks Supervisor
to send SIGINT to Valheim and wait for its final save. It archives the **entire**
save directory, including the 1.0 world directory tree and permission lists,
into `/data/backups/recovery.tar` and writes a SHA-256 checksum. The hook then
restarts the game, even if archiving fails; a failure marks the backup failed.
Players experience a brief disconnect during this step.

The immutable recovery archive is the recovery source. Live world files may
change while Velero copies the volume; do not use those files for a coordinated
restore. Monthly restore qualification verifies the archive checksum, tar
structure, and a committed 1.0 world marker in `games-restore`. The restored
container skips Steam downloads and refuses to start the game outside `games`.
This verifies archive integrity, not a full in-game world load.

Before an intentional update, create a completed backup and qualify its restore:

```sh
velero backup create valheim-before-change --from-schedule services-daily --wait
velero backup describe valheim-before-change --details
velero backup logs valheim-before-change
```

For recovery, keep the production StatefulSet stopped while a temporary
maintenance pod mounts its PVC. Verify `backups/recovery.sha256` from the
`backups` directory, move the old `worlds` directory aside, create an empty
`worlds` directory owned by UID/GID 1000, and extract `backups/recovery.tar` there.
Remove the maintenance pod before resuming the single game server. Start it
with a compatible game version and verify a real player can load the world.
World upgrades can be one-way; changing the container digest does not roll back
either the Steam installation or the world.

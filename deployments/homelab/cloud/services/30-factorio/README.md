# Factorio Space Age

Factorio runs as one stateful workload in the `services-v1` cluster. This is a
single-writer simulation, so high availability means rescheduling the same
Cinder volume on a healthy worker rather than running unsafe active replicas.

| Surface | Value |
| --- | --- |
| Server version | Factorio 2.0.77 stable, digest-pinned rootless image |
| Expansion | Space Age, Quality, and Elevated Rails enabled |
| Provider VIP | `10.21.40.123:34197/udp` |
| Internet path | CCR2004 WAN `34197/udp` to the provider VIP |
| State | Retained 20 GiB `rbd1` volume |
| Runtime | 2 CPU and 4 GiB requested; 8 GiB memory ceiling; no CPU throttle |

The server is published in Factorio's public multiplayer browser as
`Fahrican Space Age`, but requires the separately shared game password. Player
account verification is disabled, so the password is the sole admission gate
and player names are not authenticated. Friends need Space Age; the normal
Steam stable branch currently supplies the matching 2.0.77 client. RCON binds
only to pod loopback and is never part of a Service or RouterOS forward.

The automatic administrator list is intentionally empty because an unverified
player could otherwise impersonate a listed administrator name. Run operational
commands through loopback RCON from an authenticated Kubernetes session, for
example:

```console
kubectl -n games exec statefulset/factorio -c factorio -- \
  /bin/rcon /players
```

Re-enable player verification before granting persistent in-game administrator
rights based on a player name.

From the trusted LAN, use the LAN game browser or direct-connect to
`10.21.40.123:34197`. Remote friends can use the public game browser or the
site's public IP. The WAN path keeps UDP port 34197 unchanged through the CCR
and OpenStack load balancer so Factorio's public endpoint detection sees the
correct source port.

## Backup and recovery

Before every scheduled Velero backup, the pod hook runs `/server-save velero`
over loopback RCON. Factorio completes `velero.zip` before Kopia copies the
volume to the services-specific Backblaze B2 prefix. Daily backups retain 30
days and weekly backups retain 90 days. Twelve ten-minute in-volume autosaves
provide a separate two-hour operational rollback window.

The monthly services restore qualification also maps `games` to an isolated
`games-restore` namespace. The restored StatefulSet recognizes that it is not
in the production namespace and refuses to launch the game server; its
integrity sidecar tests every recovered save archive before the qualification
can succeed.

Before a version or mod change, create and inspect an on-demand backup:

```console
velero backup create factorio-before-change \
  --from-schedule services-daily --wait
velero backup describe factorio-before-change --details
velero backup logs factorio-before-change
```

Do not accept an upgrade until the backup is `Completed` and an isolated
restore has passed. Factorio saves are forward-migrated; rolling the container
image back does not make a newer world compatible with an older server.

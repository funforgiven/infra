# Factorio Space Age

Factorio runs as one stateful workload in the homelab cluster. This is a
single-writer simulation, so high availability means rescheduling its RBD volume
on another node rather than running unsafe active replicas.

| Surface | Value |
| --- | --- |
| Server version | Factorio 2.0.77 stable, digest-pinned rootless image |
| Expansion | Space Age, Quality, and Elevated Rails enabled |
| MetalLB VIP | `10.21.40.123:34197/udp` |
| Internet path | CCR2004 WAN `34197/udp` to the MetalLB VIP |
| Load-balancer policy | `externalTrafficPolicy: Cluster` from any node |
| State | 20 GiB `ceph-block` volume |
| Runtime | 2 CPU and 4 GiB requested; 8 GiB memory ceiling; no CPU throttle |

The server is published in Factorio's public multiplayer browser as `Fahrican
Space Age`. Joining requires both a verified Factorio account and the
separately shared game password. Friends need Space Age; the normal Steam stable
branch supplies the matching 2.0.77 client. RCON binds only to pod
loopback and is never part of a Service or RouterOS forward.

The automatic administrator list is empty so privileged operations stay
confined to loopback RCON from an authenticated Kubernetes
session, for example:

```console
kubectl -n games exec statefulset/factorio -c factorio -- \
  /bin/rcon /players
```

Grant persistent in-game administrator rights only as a reviewed operational
change, even though player names are verified.

From any local LAN, use the public game browser; the trusted VLAN may also
direct-connect to `10.21.40.123:34197`. Remote friends use the public game
browser or direct-connect to the site's public IP on port `34197`. The WAN path
forwards UDP 34197 to the MetalLB VIP. The CNI may randomize an outbound probe's
source port, so a narrow CCR source-NAT rule pins only VIP-originated UDP
traffic to destination port 34197 back to public source port 34197. Factorio's
public endpoint detection therefore advertises the same port accepted by the
inbound rule. A UDP-only NAT reflection lets local LAN clients use that same
public endpoint. MetalLB announces the VIP from one node, and cluster
forwarding carries a new flow to the singleton Factorio pod. Save-archive verification runs continuously for observability but
does not control game readiness; only the Factorio process can remove the
player endpoint from service.

## Backup and recovery

Before every scheduled Velero backup, the pod hook runs `/server-save velero`
over loopback RCON. Factorio completes `velero.zip` before Kopia copies the
volume to the cluster's Backblaze B2 prefix. Daily backups retain 30
days and weekly backups retain 90 days. Twelve ten-minute in-volume autosaves
provide a separate two-hour operational rollback window.

The monthly restore check also maps `games` to an isolated
`games-restore` namespace. The restored StatefulSet recognizes that it is not
in the production namespace and refuses to launch the game server; its
integrity sidecar tests every recovered save archive before the check can
succeed.

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

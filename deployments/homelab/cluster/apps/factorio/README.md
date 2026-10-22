# Factorio Space Age

One Factorio server runs in `games` as a single writer: high availability means
rescheduling its RBD volume, never a second replica. It is listed publicly as
`Fahrican Space Age`; joining needs a verified Factorio account and the shared
game password.

## Why it is built this way

- **The world type is explicit.** `render-config.sh` writes `mod-list.json`
  with Space Age, Quality and Elevated Rails so an image default cannot change
  the world. It also renders the credentials into memory-only volumes rather
  than the backed-up PVC, which is why the image's own entrypoint (which stores
  the RCON password and settings under `/factorio/config` and binds RCON on all
  interfaces) is not used.
- **RCON is loopback-only.** It is never part of a Service or router forward;
  privileged commands go through an authenticated Kubernetes session, e.g.
  `kubectl -n games exec statefulset/factorio -c factorio -- /bin/rcon /players`.
  The admin list stays empty; granting in-game admin is a reviewed change.
- **Source-NAT port pinning.** The CNI may randomize an outbound probe's source
  port, so a narrow CCR source-NAT rule maps VIP-originated UDP to port 34197
  back to public source port 34197. Factorio then advertises the same public
  port the inbound forward accepts; UDP NAT reflection lets LAN clients use it.
- **Saves migrate forward only.** Rolling the image back does not make a newer
  world load on an older server. Take a completed backup, and pass an isolated
  restore, before a version or mod change.

## Backup

Before each backup the pod hook runs `/server-save velero` over RCON so the
copy contains a complete save; the `save-integrity` sidecar tests every save
archive but never gates readiness. Twelve ten-minute autosaves give a separate
two-hour rollback window. Schedules and restore drills are owned by
`infrastructure/backups/`.

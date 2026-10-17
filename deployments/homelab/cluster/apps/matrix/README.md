# Private Matrix community

Synapse, PostgreSQL 17, Matrix Authentication Service (MAS), Element Web and
the encrypted alert relay run in the `matrix` namespace of the single physical
homelab cluster. Accounts are `@name:matrix.fahrican.com`. Federation, remote
media downloads, public registration, guests and URL previews are disabled.
The separate ZITADEL membership project admits friends without granting
infrastructure access. Accounts, OIDC clients, signing/session keys, the bot
device and approved recipient devices must be preserved on restore.

| Endpoint | Access |
| --- | --- |
| `https://matrix.fahrican.com` | Public client API; federation, signing-key and Synapse admin routes rejected |
| `https://matrix-auth.fahrican.com` | Public MAS login/OAuth; administration stays private |
| `https://element.fahrican.com` | Public Element Web fixed to this homeserver |
| `https://auth.cloud.fahrican.com` | Public ZITADEL discovery/login assets; management stays private |
| `https://matrix-alerts.fahrican.com/notify` | Trusted LAN/WireGuard; scoped producer bearer authentication |

The dedicated public Envoy VIP is `10.21.40.128`, with RouterOS forwarding
WAN TCP 443 and narrow LAN reflection. The private gateway is
`10.21.40.122`; ZITADEL management uses `10.21.20.131`. The canonical client is
`element.fahrican.com`; `chat.fahrican.com` redirects there. Public records use
the WAN IPv4 with Cloudflare proxying disabled. Cert-manager uses
public resolvers for DNS-01 checks; see its
[split DNS guidance](https://cert-manager.io/docs/configuration/acme/dns01/#setting-nameservers-for-dns01-self-check).

## Recovery

Keep the Matrix Flux Kustomization suspended until both PostgreSQL databases,
local media and relay state are restored and verified. Restore logical dumps of
Synapse and MAS into PostgreSQL 17; a filesystem copy of live PostgreSQL is
insufficient. Use both databases from the **same completed dump generation**.

Restore the encrypted `runtime.sops.yaml` and `email.sops.yaml`, the media PVC
and the relay PVC. The relay snapshot under `relay/backups` holds its SQLite
queue, crypto store, bot device `INFRA_ALERTS` and encrypted Megolm canary;
place the recovered crypto databases and queue at the root of the relay state
directory. Verify the queue, bot/device identity and canary offline before
releasing the application. Do not enroll a second bot with that device against
an empty crypto store.

Start PostgreSQL, MAS, Synapse and the relay in that order. Compare the bot
fingerprint, test decryption from a recovered recipient, then reopen routes.
Check member SSO, room history, local media, encrypted firing/resolved alerts
and background mobile delivery. Account login alone cannot recover encrypted
history; members keep their Element recovery keys and device backups.

The monthly isolated restore controller restores PVCs and inert verifier Pods
into the deny-all `matrix-restore` namespace, restores both logical databases
into disposable PostgreSQL, checks queue integrity and decrypts the recovered
canary. See the [backup policy](../../infrastructure/backups/README.md). This
checks the recovery data; browser SSO, push and a complete live restore are
separate checks.

## Administration

The access wrapper reads the K3s administrator config over pinned SSH to
pecorino and keeps it in a Linux memory file. Run from the administration
workstation with its enrolled key and private network access:

```sh
nix run .#matrix-access -- cluster -- kubectl -n matrix get pods,pvc
nix run .#matrix-access -- cluster -- nix run .#matrix-admin -- qualify
```

Build the runtime image and run the disposable local test with:

```sh
nix run .#matrix-qualify-local
nix build .#matrix-runtime-image
```

Publish and pin a replacement image with `matrix-admin publish-image` only after
review and a passing local test. The `images:` entry in `kustomization.yaml`
pins the digest for every workload; the restore modifiers in `restore.yaml`
carry their own pinned reference, which `publish-image` updates. Deployment
Secrets contain the enrolled identity and session material. For OIDC
configuration changes, refresh the provider outputs through
`render-cluster-credentials` rather than generating new client identities.

## Membership

Create friends as ZITADEL users through the private management interface and
grant only the Matrix project's `matrix-member` role. Their first login
provisions a local account through MAS; then invite them to local rooms. Adding
someone to **Infra Alerts** also requires enrolling the allowed user and
pinning their devices; ordinary chat rooms do not use the relay's pin list.
Local members can upload local media, so moderate membership and storage even
though remote servers cannot supply content.

Rotate an individual intake token, then re-enroll that host before rollout.
For Resend rotation, reconcile its provider key, regenerate the Alertmanager and
host files, and reinstall each host profile. Replacing the bot credential or
crypto store is a planned identity change that requires recipient
re-verification; do not silently reset the device.

## Encrypted delivery and devices

Each intended recipient must join **Infra Alerts** and keep an approved
active device. Compare its Ed25519 public fingerprint through a trusted channel
before approving it:

```sh
nix run .#matrix-admin -- approve-device --user @NAME:matrix.fahrican.com \
  --device DEVICE_ID --fingerprint 'VERIFIED ED25519 PUBLIC FINGERPRINT'
```

In Element Web, open avatar → All Settings → Encryption → Advanced and use
Session ID and the public Session key. A recovery key or access token is not a
device fingerprint. Device changes pause delivery and the heartbeat until
approved; intake stays durable and the relay does not fall back to plaintext.
Cross-signing is described in the
[Matrix specification](https://spec.matrix.org/v1.16/client-server-api/#cross-signing).

Alertmanager sends to the internal relay Service. External host producers use
the private intake route with their own scoped tokens. Enroll a host with
`configure-alerting --phase PHASE --host NAME`, using the phase in
`rollout.json`. Keep unrelated producer identities and fallback credentials.

Cilium enforces the Matrix, ZITADEL, DNS, mail and push-gateway allowlists.

## Telegram retirement

`rollout.json` records the alerting phase. It is `dual`: Alertmanager sends to
both Matrix and the infrastructure Telegram bot, and critical/error alerts also
go to email. Retire Telegram after at least seven days of verified dual
delivery. From outside the LAN, trigger a database backup and isolated restore,
test Element decryption and recovery, and test push with the phone locked:

```sh
nix run .#matrix-access -- cluster -- kubectl -n matrix create job \
  --from=cronjob/matrix-database-backup matrix-dump-check
nix run .#matrix-access -- cluster -- velero backup create matrix-check \
  --from-schedule services-daily --wait
nix run .#matrix-access -- cluster -- kubectl -n backup-qualification create job \
  --from=cronjob/matrix-restore-qualification matrix-restore-check
nix run .#matrix-access -- cluster -- kubectl -n backup-qualification wait \
  --for=condition=Complete job/matrix-restore-check --timeout=110m
nix run .#matrix-access -- cluster -- nix run .#matrix-admin -- qualify \
  --mobile-and-recovery-checked
nix run .#matrix-admin -- configure-alerting --phase matrix
```

`qualify` checks the rejected public federation/admin/remote-media routes, the
AWS alarms and an isolated restore within 40 days. `--phase matrix` requires
seven days since dual delivery started and a `qualify` run less than 24 hours
old. Commit and deploy the Alertmanager change, verify Matrix and email, then
remove the bot:

```sh
nix run .#matrix-admin -- retire-telegram
```

Commit the credential, runtime-contract and bot-catalog changes. Revoke the
infrastructure bot token through BotFather (manual) and delete the
`services-observability/infrastructure-telegram` Secret. To roll back before
retirement, run `configure-alerting --phase dual`, commit and redeploy; the
Matrix queue keeps undelivered events.

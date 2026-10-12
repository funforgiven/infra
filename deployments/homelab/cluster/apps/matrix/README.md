# Private Matrix community

Synapse, PostgreSQL 17, Matrix Authentication Service (MAS), Element Web and
the encrypted alert relay run in the `matrix` namespace of the single physical
homelab cluster. Accounts remain `@name:matrix.fahrican.com`. Federation, remote
media downloads, public registration, guests and URL previews remain disabled.
The separate ZITADEL membership project admits friends without granting
infrastructure access. Existing accounts, OIDC clients, signing/session keys,
bot device and approved recipient devices must survive migration.

| Endpoint | Access |
| --- | --- |
| `https://matrix.fahrican.com` | Public client API; federation, signing-key and Synapse admin routes rejected |
| `https://matrix-auth.fahrican.com` | Public MAS login/OAuth; administration stays private |
| `https://element.fahrican.com` | Public Element Web fixed to this homeserver |
| `https://auth.cloud.fahrican.com` | Public ZITADEL discovery/login assets; management stays private |
| `https://matrix-alerts.fahrican.com/notify` | Trusted LAN/WireGuard; scoped producer bearer authentication |

The dedicated public Envoy VIP remains `10.21.40.128`, with RouterOS forwarding
WAN TCP 443 and narrow LAN reflection. The private services gateway remains
`10.21.40.122`; ZITADEL management uses `10.21.20.131`. The canonical client is
`element.fahrican.com`; `chat.fahrican.com` redirects there. Public records use
the existing WAN IPv4 with Cloudflare proxying disabled. Cert-manager uses
public resolvers for DNS-01 checks; see its
[split DNS guidance](https://cert-manager.io/docs/configuration/acme/dns01/#setting-nameservers-for-dns01-self-check).

## Recovery and migration

Follow [DATA-MIGRATION.md](../../../../../docs/migration/DATA-MIGRATION.md)
and [RUNBOOK.md](../../../../../docs/migration/RUNBOOK.md). Keep the Matrix Flux
stage suspended until both PostgreSQL databases, local media and relay recovery
state are restored and verified. The database-only bootstrap helper starts the
existing PostgreSQL writer with its required dependencies while Synapse, MAS,
relay and backup schedulers remain stopped. Restore logical dumps of Synapse
and MAS into PostgreSQL 17; a filesystem copy of live PostgreSQL is insufficient.
The bootstrap migrates the known old pod-network pg_hba rule to `10.100.0.0/16`
while retaining local and custom entries.

Restore the existing encrypted `runtime.sops.yaml` and `email.sops.yaml`, media
PVC and relay PVC. The relay snapshot contains its SQLite queue, crypto store,
original bot device `INFRA_ALERTS` and encrypted Megolm canary. Verify the queue,
bot/device identity and canary offline before releasing the application stage.
Do not enroll a second bot with that device against an empty crypto store.
Check member SSO, existing room history, local media, encrypted firing/resolved
alerts and background mobile delivery after restoration. Keep Telegram and the
independent email transport until encrypted recovery and the observation period
are qualified.

The monthly isolated restore controller restores PVCs and inert verifier Pods
into the deny-all `matrix-restore` namespace, restores both logical databases
into disposable PostgreSQL, checks queue integrity and decrypts the recovered
canary. See the [backup policy](../../infrastructure/backups/README.md). A
successful configuration/schema check does not establish a successful live
restore. Dated enrollment and source restore evidence is retained in
[SOURCE-RECOVERY.md](SOURCE-RECOVERY.md); its old access/provisioning instructions
describe the retiring deployment.

## Administration after cutover

The target access wrapper reads the new K3s administrator config over pinned
SSH to pecorino and keeps it in a Linux memory file. Run from the administration
workstation with its enrolled key and private network access:

```sh
nix run .#matrix-access -- cluster -- kubectl -n matrix get pods,pvc
nix run .#matrix-access -- cluster -- nix run .#matrix-admin -- qualify
```

The wrapper accepts `cluster`. Source-cluster access during migration uses the
frozen source checkout explicitly, as documented in DATA-MIGRATION. The target
does not obtain kubeconfigs or credentials through Magnum or a cloud provider.

Runtime image builds and local disposable qualification remain available:

```sh
nix run .#matrix-qualify-local
nix build .#matrix-runtime-image
```

Publish and pin a replacement image only after review and successful disposable
qualification. Capture the currently pinned image independently before the
Forgejo registry outage. Existing deployment Secrets already contain enrolled
identity and session material; migration restores those inputs. For intentional
OIDC configuration changes, refresh reviewed retained provider outputs through
`render-cluster-credentials` rather than generating replacement client identities.

## Encrypted delivery and devices

Each intended recipient must join **Infra Alerts** and retain an approved
active device. Compare its Ed25519 public fingerprint through a trusted channel
before approving it:

```sh
nix run .#matrix-admin -- approve-device --user @NAME:matrix.fahrican.com \
  --device DEVICE_ID --fingerprint 'VERIFIED ED25519 PUBLIC FINGERPRINT'
```

In Element Web, open avatar → All Settings → Encryption → Advanced and use
Session ID and the public Session key. A recovery key or access token is not a
device fingerprint. Device changes pause delivery and the independent heartbeat
until approved; intake remains durable and the relay does not fall back to
plaintext. Cross-signing is described in the
[Matrix specification](https://spec.matrix.org/v1.16/client-server-api/#cross-signing).

Alertmanager sends to the internal relay Service. External host producers use
the private intake route with their own scoped tokens. Native Windows/macOS
runner producers are retired; new host monitoring is an explicit enrollment
operation. Preserve unrelated producer identities and fallback credentials.
Use `configure-alerting --phase dual` for reviewed routing changes, qualify
both transports and the required observation period, and retire Telegram only
after its explicit recovery checks pass. The migration does not retire Telegram.

Calico native and Kubernetes policy allowlists retain the intended Matrix,
ZITADEL, DNS, mail and restricted push-gateway paths. Target policies use the
single cluster's pod CIDR and explicitly deny unwanted traffic. New infrastructure
does not depend on the old Magnum global policy or guest DHCP host routes.

No target Matrix deployment or live account/room change has occurred during
migration preparation.

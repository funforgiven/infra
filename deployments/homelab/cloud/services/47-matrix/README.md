# Private Matrix community

Synapse, PostgreSQL 17, Matrix Authentication Service (MAS), Element Web, and
the encrypted alert relay run in `services-v1`. Accounts have the form
`@name:matrix.fahrican.com`. Friends need accounts on this server. Federation,
remote media downloads, public registration, guests, and URL previews are
disabled. A separate ZITADEL project admits Matrix members without granting
infrastructure access.

| Endpoint | Access |
| --- | --- |
| `https://matrix.fahrican.com` | Public client API; federation, signing-key and Synapse admin routes rejected |
| `https://matrix-auth.fahrican.com` | Public MAS login and OAuth endpoints; admin resource is not enabled |
| `https://chat.fahrican.com` | Public Element Web, fixed to this homeserver |
| `https://auth.cloud.fahrican.com` | Public discovery, OIDC, login UI and assets; management APIs and console stay private |
| `https://matrix-alerts.fahrican.com/notify` | LAN/WireGuard only; scoped bearer authentication per producer |

The dedicated public Envoy VIP is `10.21.40.128`. RouterOS forwards only WAN
TCP 443 to it and supplies narrow LAN reflection. The existing private gateway
at `10.21.40.122` serves host alert intake. Public DNS uses the homelab's static
IPv4 with Cloudflare proxying disabled. Services cert-manager performs DNS-01
checks through public resolvers so the private `cloud.fahrican.com` zone cannot
hide ACME challenge records; this follows the
[cert-manager split DNS guidance](https://cert-manager.io/docs/configuration/acme/dns01/#setting-nameservers-for-dns01-self-check). Private `cloud.fahrican.com` resolution
continues to reach the undercloud gateway, including private ZITADEL management.

The Matrix wave is enabled after identity and runtime enrollment. Generated signing keys, database
passwords and MAS secrets are encrypted in `runtime.sops.yaml`, and the scoped
email key is encrypted in `email.sops.yaml`. The tested runtime is published and
pinned by digest in `kustomization.yaml`. OIDC and bot enrollment are still
required before alert delivery. The supplied static WAN address, `31.223.15.252`,
is recorded in the DNS inputs.

## Enrollment and activation

Run from the repository root. Use `nix run path:.#…` while these files are
untracked; normal `nix run .#…` works once they are committed. Commands capture
credentials in memory and write SOPS ciphertext. Never print decrypted runtime
documents, issue compatibility tokens interactively, or put tokens in arguments.

Cluster access is generated on demand; this workstation intentionally has no
persistent services kubeconfig. `matrix-access undercloud` reads the control-plane
admin config over pinned SSH and keeps it in a Linux memory file.
`matrix-access services` uses the existing Magnum identity to generate the
`services-v1` config in a private RAM directory, then removes it when the command
exits. Both set `KUBECONFIG` for the enclosed command:

```sh
nix run .#matrix-access -- services -- kubectl get nodes
nix run .#matrix-access -- undercloud -- kubectl get terraform -A
```

Run this from the administration workstation with its enrolled
`/run/secrets/github-ssh-key`, the per-host sudo password, pinned SSH known hosts,
and private network connectivity. The undercloud is used to obtain access and
read identity/DNS/AWS controller outputs; Matrix workloads run in `services-v1`.

1. Build and test the disposable local stack, then publish the runtime image:

   ```sh
   nix run .#matrix-qualify-local
   nix build .#matrix-runtime-image
   nix run .#matrix-admin -- publish-image "$(readlink -f result)"
   ```

   Publication uses the enrolled Forge runner registry identity, pins the
   resulting digest, and creates pull Secrets for Matrix and restore jobs.
   PostgreSQL, Synapse, MAS, Element Web, nginx, Squid and the encryption library
   come from the locked Nix inputs. Rebuild and republish when those inputs or
   `nginx.conf` change. Other Python scripts are mounted from Flux ConfigMaps.

2. Enroll the public address and the dedicated ZITADEL client:

   ```sh
   nix run .#matrix-admin -- configure-dns --wan-ipv4 31.223.15.252
   nix run .#matrix-access -- undercloud -- nix run .#matrix-admin -- sync-identity
   ```

   Commit the identity OpenTofu change first and wait for its outputs before
   `sync-identity`. Reconcile the RouterOS inventory, public DNS and certificates.
   ZITADEL Login V2 is already routed through the private undercloud gateway;
   the public nginx allowlist forwards only the required login paths to it.

3. Refresh the restricted AWS provisioning policy with the workstation’s
   administrative SSO profile:

   ```sh
   aws sso login --profile default
   nix run .#matrix-admin -- sync-monitoring-policy --aws-profile default
   ```

   This verifies that SSO and the enrolled provisioning identity use the same
   AWS account, reconciles only the declared `fahrican-matrix-monitoring-gitops` policy,
   attaches it to `fahrican-mail-gitops`, and retains the existing access key.
   Matrix permissions live in a separate policy to stay below IAM’s per-policy
   size limit. Set
   `enable_matrix_monitoring` to `"true"` in
   `undercloud/84-mail-aws/tofu.yaml`, commit, and wait for OpenTofu to converge.
   Confirm the existing Gmail SNS subscription. Enroll the heartbeat afterward:

   ```sh
   nix run .#matrix-access -- undercloud -- nix run .#matrix-admin -- enroll-monitoring
   nix run .#reconcile-services-resend -- apply --key matrix
   ```

   Resend writes the domain-scoped Matrix sending key to `email.sops.yaml`.
   The mail appliance currently offers inbound SMTP and authenticated JMAP;
   Resend supplies authenticated SMTP for alert fallback. AWS SNS supplies the
   separate path for homelab-wide outages.

4. Unsuspend through the guarded repository command, commit, and wait for Flux:

   ```sh
   nix run .#matrix-admin -- activate
   nix run .#matrix-access -- services -- kubectl -n matrix get pods,pvc
   nix run .#matrix-access -- services -- kubectl -n services-network get gateway matrix-public
   ```

   `activate` refuses missing OIDC enrollment, image publication or DNS inputs.
   Open Element Web, Desktop or Element X with homeserver
   `https://matrix.fahrican.com`, sign in through ZITADEL and complete account
   creation. Record the actual local Matrix ID. Set up cross-signing and secure
   key backup; retain the recovery key in the password manager. Test a second
   device and recovery before relying on encrypted history.

5. Create the non-admin alert account and encrypted rooms:

   ```sh
   nix run .#matrix-access -- services -- nix run .#matrix-admin -- enroll-bot \
     --owner @YOUR_LOCAL_NAME:matrix.fahrican.com
   ```

   Commit the encrypted runtime change, join **Infra Alerts** in Element, and
   compare each recipient device's Ed25519 fingerprint through a trusted channel.
   Pin every device that should receive alerts:

   ```sh
   nix run .#matrix-admin -- approve-device --user @YOUR_LOCAL_NAME:matrix.fahrican.com \
     --device DEVICE_ID --fingerprint 'ED25519 FINGERPRINT FROM ELEMENT'
   ```

   Fingerprints are public device keys. Spaces in Element's displayed key are
   accepted. A new or changed device pauses delivery until explicitly approved;
   the relay never falls back to plaintext. The bot retains device
   `INFRA_ALERTS` and its crypto store on the `matrix-relay` PVC. Do not enroll a
   second bot with the same device against a fresh store.

The services workers have DHCP host routes for `1.1.1.1` and `8.8.8.8`
through an isolated secondary network. Certificate validation uses reachable
public resolvers `9.9.9.9` and `149.112.112.112`.

Magnum's Calico addon installs a global outbound allow at order 20. Matrix's
Calico policies run at order 15, allow only the documented workload paths and
end with explicit denial. The isolated restore namespace also has an early
inbound and outbound denial. Keep the Calico and Kubernetes allowlists in sync.
[Calico documents ordered evaluation and terminal Allow/Deny actions](https://docs.tigera.io/calico/latest/reference/resources/globalnetworkpolicy).

## Alert migration

Start dual delivery only after Matrix works on all intended devices. Enroll
each NixOS host that uses the monitoring module; the current native host is
`forge-macos`, whose `quickemu-macos` failure hook uses this transport.

```sh
nix run .#matrix-admin -- configure-alerting --phase dual --host forge-macos
nix run .#enroll-service-host-secrets -- SSH_TARGET matrix-monitoring:forge-macos
```

Commit the generated Matrix Alertmanager overlays, host SOPS files and
`rollout.json`, deploy the host configuration, and verify both Telegram and
Matrix receive firing and resolved alerts. Repeat `--host` for additional host
producers. Each host's root-owned `/var/lib/monitoring-bootstrap/matrix.json`
contains its own intake token and TLS SMTP fallback. Retry configuration with
the same host ID preserves its token. Deploy promptly after recording the dual
start time; restart the seven-day observation period if rollout was delayed.

The relay accepts Alertmanager only at its internal Service. Host tokens work
only on `/notify`; they cannot impersonate another producer or choose a room.
Acknowledgement follows a committed SQLite write. Stable event transactions
allow retry after an ambiguous response or restart. Delivered bodies are
erased from the queue; pending alert bodies remain local until delivery.

Critical and error Alertmanager notifications also go directly to the external
email address. A host uses SMTP when the relay cannot durably accept its alert.
AWS checks the public Matrix, MAS and ZITADEL endpoints every minute and watches
for a heartbeat sent only after an encrypted canary succeeds. Missing delivery
for five minutes or public failure for three minutes alarms through SNS. Push
notifications use the allowed `matrix.org` gateway through Squid; no message
content is included. Verify actual background Element X push on cellular data.

After at least seven days of verified dual delivery, run qualification from
outside the LAN. First trigger a database backup and isolated restore, test
Element decryption and recovery, and test push while the phone is locked:

```sh
nix run .#matrix-access -- services -- kubectl -n matrix create job \
  --from=cronjob/matrix-database-backup matrix-dump-check
nix run .#matrix-access -- services -- velero backup create matrix-check \
  --from-schedule services-daily --wait
nix run .#matrix-access -- services -- kubectl -n backup-qualification create job \
  --from=cronjob/matrix-restore-qualification matrix-restore-qualification-check
nix run .#matrix-access -- services -- kubectl -n backup-qualification wait \
  --for=condition=Complete job/matrix-restore-qualification-check --timeout=110m
nix run .#matrix-access -- services -- nix run .#matrix-admin -- qualify \
  --mobile-and-recovery-checked
nix run .#matrix-admin -- configure-alerting --phase matrix --host forge-macos
```

Qualification checks rejected public federation/admin/remote-media routes,
healthy independent AWS alarms, and a successful isolated restore within
40 days. Cutover requires seven days since dual delivery started and a
qualification less than 24 hours old. Commit and deploy both Alertmanager and
the NixOS transport change, verify Matrix and email, then retire the old bot:

```sh
nix run .#matrix-admin -- retire-telegram
```

Commit the credential, runtime-contract and bot-catalog removals. After the
host rollout, remove its old `bot-token` and `chat-id` files. Revoke the
infrastructure bot token through BotFather and delete the unused
`services-observability/infrastructure-telegram` Secret. BotFather revocation
is manual. To roll back transport before retirement, regenerate the `dual`
overlay, commit and redeploy; the durable Matrix queue continues to retain
undelivered events.

## Backup, recovery and membership

Daily 01:15 Istanbul logical dumps capture both databases and retain the three
newest checksum-verified generations. Velero also refreshes those dumps and
the relay's online SQLite snapshots in pre-backup hooks; a failed hook fails
the backup. It copies media, dumps and relay state to encrypted Kopia storage.
The live PostgreSQL data directory is excluded. Keep signing keys, MAS secrets,
OIDC credentials and tokens in the SOPS repository recovery set.
Each database dump is transactionally consistent; the two database snapshots
are taken sequentially. For a coordinated recovery point during identity or
account migrations, pause those changes until both dumps complete.

The monthly `matrix-restore-qualification` job applies deny-all networking
before restoring the latest completed daily backup into `matrix-restore`.
Only PVCs and inert sleeper pods are restored. Production services, identity
callbacks and notification senders never start there. A verifier restores both
databases into disposable PostgreSQL, checks queue snapshot integrity, verifies
the original bot device key, and decrypts a canary with a restored session key.
This checks the recovery data; browser SSO, push and complete live recovery
remain separate qualification steps. The latest isolated volumes remain for
inspection until the next run.

For live recovery, first qualify the chosen backup in isolation. Close public
routes and stop Matrix writers. Restore both databases from the **same completed
dump generation**, media, and `relay/backups`; place the recovered crypto DBs
and queue at the root of the relay state directory. Restore the original SOPS
runtime, signing keys, bot token and stable device ID. Start PostgreSQL, MAS,
Synapse and the relay in order, compare the bot fingerprint, test decryption
from a recovered recipient, then reopen routes. Account login alone cannot
recover encrypted history; retain Element recovery keys and device backups.

Create friends as ZITADEL users through the private management interface and
grant only the separate Matrix project's `matrix-member` role. Their first
login provisions a local account through MAS. Invite them to local rooms.
Adding someone to **Infra Alerts** also requires enrolling the allowed user
and explicitly pinning their devices; ordinary chat rooms do not use the
relay's pin list. Local members can upload local media, so moderate membership
and storage even though remote servers cannot supply content.

Rotate an individual intake token, then re-enroll that host before rollout.
For Resend rotation, reconcile its provider key, regenerate Alertmanager and
host files, and reinstall each host profile. A bot credential or crypto-store
replacement requires a planned identity change and recipient re-verification;
do not silently reset the device. Monitor queue age, failed delivery, storage,
database dump age, restore age and certificate expiry.

References: [Synapse outbound proxy](https://element-hq.github.io/synapse/latest/setup/forward_proxy.html),
[ZITADEL API paths](https://zitadel.com/docs/apis/introduction),
[Velero filesystem recovery](https://velero.io/docs/v1.18/file-system-backup/).

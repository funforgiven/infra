# Credential-final activation

All topology, controller configuration, Secret schemas, health checks, backup
policy, and application configuration are committed before this procedure.
Activation adds externally issued credentials, promotes reproducible images,
and advances already-declared waves through signed Git changes. It does not require hand-editing a
Kubernetes Secret, bucket endpoint, Cloudflare identifier, mail address, or
Alertmanager value.

Every instruction below to activate a stage means running the declarative
stage helper, reviewing its narrowly scoped diff, running the repository
checks, and pushing a signed Conventional Commit directly to `main`:

```console
nix run .#advance-services-activation -- STAGE
```

Do not use `flux resume` as the durable activation mechanism. The committed
Flux Kustomizations are authoritative, and a live-only change would be drift.

## 1. Issue credentials without broadening trust

Create three distinct Telegram bots: infrastructure alerts, Hermes
conversation, and media acquisition. Issue a Hetzner token for the mail-edge
project, Last.fm application keys, a Resend administration key, a dedicated
OpenAI project API key for Hermes, and four Backblaze B2 application keys: one
for Velero and one for each standalone host prefix. Give each key only the
declared prefix and capabilities. Keep the GHCR publishing credential in a
mode-0400 or mode-0600 containers auth file outside the repository.

Enroll each services-cluster/controller value with the no-echo app:

```console
nix run .#enroll-services-credential -- KEY
# Or, after filling the ignored mode-0600 intake file:
nix run .#enroll-services-credential -- --from-file KEY
```

Run it once for every available upstream value in `credentials`,
`postDeploymentCredentials`, and `hostCredentials`. The contract routes
cluster, Hermes, mail, and host-backup values to separate SOPS documents. The
interactive mode reads twice from the terminal; `--from-file` reads only the
predictable ignored `secrets/KEY.key` intake file after verifying it is a
non-symlink mode-0600 file. Both paths base64-encode in memory and use
`sops set --value-stdin`; the value is never a command argument or plaintext
tracked file. After successful `--from-file` enrollment, the ignored intake
file is returned to zero length. Enter
`MAIL_MANAGEMENT_CIDRS_JSON` as a JSON list such as `["198.51.100.10/32"]`,
using the real trusted public CIDR rather than the documentation example.

Locally owned high-entropy values are declared under `generatedSecrets` and
generated directly into their target SOPS document. The initial values are
already committed as ciphertext; rotate one explicitly with:

```console
nix run .#generate-services-credential -- --rotate KEY
```

Review only the ciphertext structure and diff statistics. Never run a command
that prints the decrypted document. Run the repository checks, create a signed
Conventional Commit, and push it directly to `main` with a fast-forward push.

## 2. Create the credential-backed foundation

Activate stage `foundation`. Its controllers create the OpenStack services
boundary and ZITADEL clients, while Flux publishes the non-secret Backblaze B2
destination contract for the existing retained `fahrican-cloud-recovery`
bucket. Enroll the Velero application key under `credentials.backupRuntime`
before activating stage `cluster`. Restrict it to `services/kubernetes/` with
only the declared capabilities. The reconciler validates every runtime value,
creates derived Secrets and Helm value ConfigMaps through memory-backed
storage, and bootstraps signed Flux reconciliation.

Issue one separate B2 application key for each standalone host prefix under
`services/hosts/`; never reuse the Velero key or a key between hosts. Their
Restic passwords are independently generated in SOPS.

## 3. Promote immutable images

From the clean signed credential commit, use services-project OpenStack
credentials and run:

```console
nix run .#promote-service-images
```

With `REGISTRY_AUTH_FILE` pointing to the root-only GHCR auth file, run:

```console
nix run .#promote-media-importer
```

The commands verify the source commit, publish immutable artifacts, and update
the host revision plus all media image digest pins. Review those non-secret
changes, run the full checks, create a second signed Conventional Commit, and
push it directly to `main`.

## 4. Standalone hosts

Activate stage `hosts`. After enrolling provider-issued values into SOPS, use
`enroll-service-host-secrets` for each host's root-only Restic and monitoring
profiles. Enroll the `hermes-openai` profile;
it decrypts only `OPENAI_API_KEY` in memory and streams it into the dedicated
root-only OpenAI environment file. Leave Hermes condition-gated until Karakeep
is live, because its independently revocable API key cannot be issued earlier.
The infrastructure Telegram bot is reused for host failure alerts; Hermes and
media retain their separate bots and chats.

Activate stage `mail`, confirm its retained address and reverse DNS, then
perform the explicitly destructive nixos-anywhere install against that exact
server. Enroll only its `mail-edge-backup` and `monitoring` profiles initially;
the absent mail runtime keeps Stalwart stopped while DNS and ACME are pending.
Activate stage `dns` after the cluster reconciler has copied the mail-edge
output into `service-dns-inputs`. Once the A and Resend verification records
are live, issue the domain-scoped Resend sending key, enroll it as
`STALWART_RESEND_API_KEY`, materialize `mail-runtime`, and start Stalwart after
its certificate is ready. The fallback administrator secret is generated, not
manually supplied.

## 5. Application and recovery gates

Activate in this order, waiting for each health check before committing the
next stage:

1. `observability`
2. `backup-controller`
3. `backup-policy`
4. `knowledge`

After Karakeep is live, create two independently revocable API keys in its UI:
one for Hermes and one for the release watcher. Enroll
`HERMES_KARAKEEP_API_KEY` into SOPS, materialize the `hermes-integrations`
profile with the host app, and rebuild Hermes so its
managed environment is reseeded from the separate OpenAI and integration
files. Enroll `RELEASE_WATCHER_KARAKEEP_API_KEY` in SOPS, create and push a
signed credential commit, wait for `wave81-services-foundation`, and wait for
or operationally trigger the already-declared services-cluster CronJob so
`media-runtime` gains that key. The central Karakeep key is the one
post-deployment credential in the services-cluster contract; this ordering
breaks the otherwise impossible dependency on a not-yet-running Karakeep
instance. Hermes then starts directly with its API and integration credentials.

Run the final repository gate:

```console
nix run .#services-activation-preflight
```

Then activate the remaining stages:

5. `media`
6. `home-automation`
7. `synthetic-monitoring`

Confirm the Velero storage location is Available, complete the isolated restore
qualification, and inspect one daily backup before accepting application data.
Then complete only the documented UI exceptions: Karakeep integration keys,
Navidrome first admin and scrobbling grants, Stalwart directory objects, and
Home Assistant UI-only integrations. Every accepted UI change is followed by
an encrypted backup and a drift-record update.

The final synthetic wave probes every private HTTP route, public mail ports,
Hermes/Home Assistant node exporters, and the last successful host Restic
timestamp. Purchases remain manual; the release watcher creates Karakeep cards
and notifications but never authenticates to Bandcamp or OTOTOY.

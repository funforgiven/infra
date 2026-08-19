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

Supply only the ten externally issued values listed in
`secrets/README.md`: the Backblaze master pair, dedicated Hetzner token, three
Telegram bot tokens, Last.fm pair, Resend administration key, and dedicated
OpenAI organization Admin key. Keep the GHCR publishing credential in a mode-0400
or mode-0600 containers auth file outside the repository. Do not issue or
prepare placeholders for derived application keys, numeric Telegram targets,
the operator CIDR, or locally generated passwords.

Enroll each services-cluster/controller value with the no-echo app:

```console
nix run .#enroll-services-credential -- KEY
# Or, after filling the ignored mode-0600 intake file:
nix run .#enroll-services-credential -- \
  --from-file --intake-directory /absolute/path/to/secrets KEY
```

Run it only for contract values in `credentials`, `hostCredentials`, and
`controllerCredentials`. Values
under `generatedSecrets` and `provisionedSecrets` reject external enrollment.
The contract routes cluster, Hermes, and mail values to separate SOPS
documents. The interactive mode reads twice from the terminal; `--from-file`
reads only the predictable ignored `KEY.key` below the selected intake
directory after verifying it is a non-symlink mode-0600 file. Both paths
base64-encode in memory and use
`sops set --value-stdin`; the value is never a command argument or plaintext
tracked file. After successful `--from-file` enrollment, the ignored intake
file is returned to zero length.

The pinned provider reconcilers own all derived values:

```console
nix run .#reconcile-services-backblaze -- apply \
  --bootstrap-directory /absolute/path/to/secrets
nix run .#reconcile-services-operator-network -- apply
# After BotFather creation, token enrollment, and one /activate per bot:
nix run .#reconcile-services-telegram -- apply
# After the Resend domain reports verified:
nix run .#reconcile-services-resend -- apply
```

The Backblaze reconciler consumes the master pair, applies the private SSE-B2
lifecycle declaration, creates four independently scoped S3-compatible
writers, encrypts each returned ID/key pair directly into its routed SOPS
document, and clears both master files only after full success. The network
reconciler agrees two public-address sources and encrypts the resulting host
CIDR. Telegram derives chat and user IDs from exact declared updates. Resend
creates a `sending_access` key scoped only to `fahrican.com` and never exposes
the administration key to Stalwart.

OpenAI has an earlier, separately gated control-plane stage because its
service-account identity must exist before its derived runtime key can be
issued. Create the initial organization Admin key in OpenAI's Admin keys page
with the exact name `fahrican-infra-openai-control-plane`, place it only in the
ignored mode-0600 `secrets/OPENAI_ADMIN_KEY.key` intake file, and enroll it:

```console
nix run .#enroll-services-credential -- \
  --from-file --intake-directory /absolute/path/to/secrets OPENAI_ADMIN_KEY
```

Review only ciphertext, run the repository checks, and push a signed credential
commit. Then activate stage `openai` in a separate signed commit and wait for
`tofu-system/openai-hermes` to become Ready. The official provider creates the
dedicated project, no-default-role service account, custom
`api.responses.write` role, group assignment, Luna-only allowlist, and USD 10
monthly hard limit. It also disables every OpenAI hosted tool. Before the first
apply, inspect the organization policy for web search, file search, image
generation, remote MCP, and Code Interpreter: a tool already set to deny-all or
selected-projects needs no change; an allow-all tool must be changed to
selected-projects without selecting Hermes because OpenAI does not permit a
project-level `false` under allow-all. This conditional UI prerequisite is in
`manual-exceptions.yaml`. Issue the runtime key only after the apply succeeds:

```console
nix run .#reconcile-services-openai -- apply
```

The one-time value goes directly into the admin-only Hermes SOPS document and
never enters OpenTofu state, an intake file, or command output. Commit and push
that ciphertext before running the full services preflight. If the reconciler
reports partial or unrecoverable state, replace the service account
declaratively; OpenAI does not permit deleting its keys through the project-key
delete endpoint.

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

After the OpenAI runtime key and every other required credential is ciphertext,
run `services-activation-preflight`. Then activate stage `foundation`. Its
controllers create the OpenStack services
boundary and ZITADEL clients, while Flux publishes the non-secret Backblaze B2
destination contract for the existing retained `fahrican-cloud-recovery`
bucket. The provider reconciler must already have populated the provisioned
Velero and host writer ciphertext. The cluster reconciler validates every
runtime value, creates derived Secrets and Helm value ConfigMaps through
memory-backed storage, and bootstraps signed Flux reconciliation. Restic
passwords remain independently generated in SOPS.

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

Activate stage `hosts`. After provider reconcilers have written derived values
into SOPS, use
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
are live and the domain is verified, run `reconcile-services-resend apply`.
It creates and encrypts `STALWART_RESEND_API_KEY`; then materialize
`mail-runtime` and start Stalwart after its certificate is ready. The fallback
administrator secret is generated, not manually supplied.

## 5. Application and recovery gates

Activate in this order, waiting for each health check before committing the
next stage:

1. `observability`
2. `backup-controller`
3. `backup-policy`
4. `knowledge`

After Karakeep is live, the operator creates two independently revocable API
keys in its UI, one for Hermes and one for the release watcher, and writes each
directly into its declared `provisionedSecrets` SOPS target without creating
an ignored intake placeholder. Materialize the `hermes-integrations` profile
with the host app, and rebuild Hermes so its
managed environment is reseeded from the separate OpenAI and integration
files. Create and push a signed credential commit, wait for
`wave81-services-foundation`, and wait for or operationally trigger the
already-declared services-cluster CronJob so `media-runtime` gains its key.
This provider-provisioned ordering breaks the otherwise impossible dependency
on a not-yet-running Karakeep instance. Hermes then starts directly with its
API and integration credentials.

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

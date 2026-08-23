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

Supply only the externally issued values listed in `secrets/README.md`: the
Backblaze master pair, two Telegram bot tokens, Last.fm pair, Resend
administration key, dedicated Hermes OpenAI API key, and the one-time AWS
bootstrap pair. Do not issue or prepare placeholders for derived
application keys, numeric Telegram targets, the operator CIDR, or locally
generated passwords.

Enroll each external runtime value with the no-echo app:

```console
nix run .#enroll-services-credential -- KEY
# Or, after filling the ignored mode-0600 intake file:
nix run .#enroll-services-credential -- \
  --from-file --intake-directory /absolute/path/to/secrets KEY
```

Run it only for contract values in `credentials` and `hostCredentials`. Values
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
# After BotFather creation, token enrollment, and one /activate per bot:
nix run .#reconcile-services-telegram -- apply
# After the Resend domain reports verified:
nix run .#reconcile-services-resend -- apply
```

The Backblaze reconciler consumes the master pair, applies the private SSE-B2
lifecycle declaration, creates three independently scoped S3-compatible
writers, encrypts each returned ID/key pair directly into its routed SOPS
document, and clears both master files only after full success. Telegram
derives chat and user IDs from exact declared updates. Resend
creates a `sending_access` key scoped only to `fahrican.com` and never exposes
the administration key to Stalwart.

An empty Restic prefix must be initialized once before its prefix-bound writer
can distinguish a missing repository from an unauthorized object. Run the
focused initializer:

```console
nix run .#initialize-services-restic -- apply
```

It initializes each repository locally, uploads only its encrypted initial
files through that host's existing prefix-bound key using Backblaze's native
API, and verifies the result through Restic's S3 backend. No broad or
additional application key is created. Routine host backup and restore operations
continue with the two independent prefix-bound keys. `check` makes no
changes:

```console
nix run .#initialize-services-restic -- check
```

Create the independently revocable Hermes key in the OpenAI dashboard and keep
its project permissions and hard spend limit under operator control. Put only
that runtime value in the ignored mode-0600 `secrets/OPENAI_API_KEY.key` intake
file and enroll it through the same generic path as every other external key:

```console
nix run .#enroll-services-credential -- \
  --from-file --intake-directory /absolute/path/to/secrets OPENAI_API_KEY
```

The command encrypts the value directly into the admin-recipient-only Hermes
SOPS document and truncates the intake file only after success. No OpenAI Admin
key, project identifier, policy, budget, or Terraform state is required by the
repository. Hermes still selects `gpt-5.6-luna` in its declarative application
configuration because API requests—not API keys—select a model. Change that
default in the Hermes NixOS module if the desired model changes.

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

After the OpenAI runtime key and every credential that can exist before service
deployment is ciphertext, run the foundation preflight:

```console
nix run .#services-activation-preflight -- foundation
```

This phase deliberately defers only the scoped Resend sending key because its
provider workflow is not ready yet. It also does
not require image promotion, which depends on the foundation. Then activate
stage `foundation`. Its controllers create the OpenStack services boundary,
while Flux publishes the non-secret Backblaze B2
destination contract for the existing retained `fahrican-cloud-recovery`
bucket. The provider reconciler must already have populated the provisioned
Velero and host writer ciphertext. The cluster reconciler validates every
runtime value, creates derived Secrets and Helm value ConfigMaps through
memory-backed storage, and bootstraps signed Flux reconciliation. Restic
passwords remain independently generated in SOPS.

Wait for `wave81-services-foundation` to become Ready, then activate stage
`cluster`. Once `wave82-services-cluster` has applied the declared CronJob,
trigger one revision-named execution instead of waiting for its next two-hour
schedule:

```console
kubectl -n openstack create job \
  --from=cronjob/services-cluster-reconcile-v1 \
  services-cluster-bootstrap-SIGNED_REVISION_SHORT
```

Wait for that Job to become Complete and independently confirm that all five
services-cluster nodes are Ready. `wave82-services-cluster` readiness alone
means the reconciler manifest was accepted; it is not cluster qualification.
Do not promote images or enable standalone hosts before both checks pass.

## 3. Promote immutable images

From the clean signed credential commit, use services-project OpenStack
credentials and run:

```console
nix run .#promote-service-images
```

The command verifies the source commit and publishes the immutable Hermes
candidate and the SHA-256-pinned official HAOS 18.2 image. It deliberately does
not change the active host revision: an active-revision change is a separate
retained-volume migration with credential staging and recovery gates, not part
of image publication.

Run the promoted-host preflight before advancing the host wave:

```console
nix run .#services-activation-preflight -- hosts
```

It retains the same provider deferral as the foundation phase and also
requires the immutable service-host image promotion.

## 4. Standalone hosts

Activate stage `hosts`. After provider reconcilers have written derived values
into SOPS, use
`enroll-service-host-secrets` for each host's root-only Restic and monitoring
profiles. Enroll the `hermes-openai` and `hermes-telegram` profiles;
it decrypts only `OPENAI_API_KEY` in memory and streams it into the dedicated
root-only OpenAI environment file, while the Telegram profile independently
materializes the private bot and allowlist values. Rebuild Hermes after both
profiles exist so it starts with web search and autonomous memory disabled.
The infrastructure Telegram bot is reused for host failure alerts; Hermes
retains its separate private bot and chat.

Mail is already migrated to the AWS Frankfurt platform described in
`components/cloud/services/mail-aws/README.md`. Its dedicated GitOps identity
owns the OpenTofu lifecycle; EC2 generates the administrator and mailbox
credentials into Secrets Manager and applies the declared account plan with
`stalwart-cli`. Run `reconcile-services-resend apply` to rotate the
domain-scoped sending key in SOPS, then `publish-aws-mail-resend` to stream it
into the AWS secret. Activate `mail-aws` before `dns`; the cluster reconciler
copies only `mail-aws-outputs` into `service-dns-inputs`. Public DNS must point
at the retained EIP before reverse DNS is enabled. After mail or DNS changes,
repeat the external Resend-to-MX acceptance and authenticated IMAPS read
documented by the monitoring-vantage exception.

## 5. Application and recovery gates

Activate in this order, waiting for each health check before committing the
next stage:

1. `observability`
2. `backup-controller`
3. `backup-policy`

Run the final repository gate:

```console
nix run .#services-activation-preflight -- final
```

Then activate the remaining stages:

4. `media`
5. `home-automation`
6. `synthetic-monitoring`

Confirm the Velero storage location is Available, complete the isolated restore
qualification, and inspect one daily backup before accepting application data.
Then complete only the documented UI exceptions: Navidrome first admin and
scrobbling grants, and
Home Assistant migration onboarding, provider-NIC configuration, HTTP proxy
confirmation, native Backblaze backup location, and UI-only integrations. Keep
the host cutover variable on `nixos` until a native full encrypted backup and
emergency kit have passed an isolated HAOS restore. After changing it to `haos`,
restore that backup, configure `10.21.40.120/24` and the operator-LAN route on
the MAC-pinned provider interface, then configure automatic encrypted Backblaze
backups in the existing `services/hosts/home-assistant/` prefix. Home Assistant's built-in HTTP settings must trust only
`192.168.80.0/24` and use forwarded headers; verify and confirm the pending
configuration through `https://home.fahrican.com` within its five-minute safety
trial. Retain the old NixOS volume until a post-cutover B2 restore passes. Every
accepted UI change is followed by an encrypted backup and a drift-record update.

The final synthetic wave probes every private HTTP route, public mail ports,
Hermes/Home Assistant node exporters, and the last successful host Restic
timestamp. Purchases and discovery remain manual; purchased albums are uploaded
directly through SFTPGo and then scanned by Navidrome.

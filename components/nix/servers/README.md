# Declarative service hosts

Hermes and the legacy Home Assistant installation are NixOS closures built from
this repository. Home Assistant is migrating to the official HAOS appliance;
its version and archive digest are pinned by the same signed image-promotion
gate. Mail runs on the dedicated AWS Frankfurt NixOS appliance declared under
`components/cloud/services/mail-aws`.
The operator account authenticates only with the pinned SSH key and has
passwordless sudo because service hosts intentionally have no login password.

Use the no-echo enrollment app for every declared host profile:

```console
nix run .#enroll-service-host-secrets -- SSH_TARGET PROFILE
```

It decrypts only the contract keys for the selected profile in memory and
streams root-only mode-0400 files through SSH standard input. Provider-issued
values are enrolled into workload-specific, admin-recipient-only SOPS
documents first; locally owned passwords are generated directly as ciphertext.

## Hermes enrollment

Hermes uses the direct `openai-api` provider with `gpt-5.6-luna` as its default
model. The operator creates and constrains its independently revocable project
key in the OpenAI dashboard, then the generic credential enrollment app moves
`OPENAI_API_KEY` from its ignored mode-0600 one-way intake file into the
admin-recipient-only `deployments/homelab/cloud/host-runtime/hermes.sops.yaml`
document. No OpenAI Admin credential, project policy, budget, or identifier is
managed here. The
`hermes-openai` host profile decrypts that one value in memory and streams a
root-only `/var/lib/hermes-bootstrap/openai.env` file over SSH standard input.
The model remains declarative because Hermes must name a model in each API
request; an API key authenticates the request but does not select its model.

The separate `hermes-telegram` profile reads the independently routed Telegram
values and creates `/var/lib/hermes-bootstrap/telegram.env` with
`TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALLOWED_USERS`, and `TELEGRAM_HOME_CHANNEL`.
This split permits OpenAI and Telegram rotation without re-enrolling the other
credential boundary. Hermes remains condition-gated until both files exist. Apply the
NixOS closure again after enrollment so the Hermes module reseeds its
service-owned `.env`; no interactive provider authentication is required.

If ciphertext is lost or the key must rotate, issue a replacement project key,
enroll and deploy it, verify Hermes, and then revoke the old key in OpenAI.

Only the Hermes bot token is externally enrolled. The pinned Telegram
reconciler derives the allowlisted user and home-channel identifiers from the
single declared private `/activate` update and writes them directly as SOPS
ciphertext. Those derived values have no intake files.

The Telegram bot is polling-only and defaults to deny; never enable the global
allow-all setting. Hermes globally disables its web toolset, autonomous memory,
embeddings, Hindsight, and external retrieval integrations.

## Off-site host backups

Each stateful host declares its Restic paths and retention policy in Nix. The
backup unit remains condition-gated until three root-only files exist:

- /var/lib/backup-bootstrap/repository: one repository or host-specific prefix
- /var/lib/backup-bootstrap/password: the repository encryption password
- /var/lib/backup-bootstrap/environment: systemd EnvironmentFile entries for
  the least-privilege object-store writer credential

All repositories use the existing `fahrican-cloud-recovery` Backblaze B2
bucket. Hermes and legacy Home Assistant are confined respectively to
`services/hosts/hermes/` and `services/hosts/home-assistant/`. The pinned Backblaze reconciler creates an
independent B2 application key restricted to each prefix so Restic can back
up, restore, and prune without crossing a host boundary. Returned material is
written directly to the admin-only SOPS document, and the master bootstrap pair
is cleared only after the complete reconciliation. The repository password is
locally generated directly into SOPS.

Materialize these files with the host enrollment app after the host is
reachable through its pinned SSH identity. Never pass values as command
arguments or write plaintext into the repository. The operator must initialize an empty
repository with `initialize-services-restic apply`, run the first backup, and
perform a restore into an isolated temporary host before enabling a production
service. The initializer creates the encrypted repository locally and uploads
only its initial files through the already prefix-bound key because Backblaze
cannot report a missing object to that caller. Scheduled operations use the
same key and remain confined to their host prefix.

The declarative Restic timer runs daily with randomized delay and retains 14 daily,
8 weekly, 12 monthly, and 3 yearly snapshots.

After HAOS cutover, Home Assistant uses its native encrypted automatic-backup
manager and native Backblaze B2 backup-location integration with the same
prefix-scoped application key. Restic stays in the contract only until a native
isolated restore passes and the retained NixOS root is retired.

## Host alert enrollment

The OpenStack service hosts export node and systemd metrics on TCP 9100
only to the services subnet. A successful Restic unit writes an atomic
textfile metric; the post-activation synthetic wave alerts when either
exporter is unavailable or its last success is older than 26 hours. The
AWS mail appliance is instead covered by public protocol probes and CloudWatch
alarms.

Critical units also use a local systemd `OnFailure` notifier. Its profile reads
the dedicated infrastructure bot token and chat identifier from the central
SOPS contract and writes mode-0400 files at
`/var/lib/monitoring-bootstrap/bot-token` and
`/var/lib/monitoring-bootstrap/chat-id`. Enroll only the token; the Telegram
reconciler discovers and encrypts the group identifier. Then materialize the
profile through encrypted SSH standard input;
do not put either value in an SSH command, Nix option, shell history, or
temporary file. The notifier supplies the token to curl through standard input,
so it is absent from the process list.

Hermes additionally needs its separate OpenAI and Telegram runtime files.
Those credentials must not reuse the infrastructure or media bots. AWS mail
generates its administrator and mailbox credentials on the instance, stores
them in Secrets Manager, and reconciles the domain and account plan through
`stalwart-cli apply`.

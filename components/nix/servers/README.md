# Declarative service hosts

The Hermes, Home Assistant, and mail-edge hosts are NixOS closures built from
this repository. OpenStack images are promoted only from a clean, signed Git
revision; the Hetzner host is installed with the pinned nixos-anywhere input.

## Hermes enrollment

Hermes remains condition-gated until OpenAI device-code enrollment creates
/var/lib/hermes/.hermes/auth.json and a root-only
/var/lib/hermes-bootstrap/runtime.env has been enrolled. The runtime file must
contain TELEGRAM_BOT_TOKEN, TELEGRAM_ALLOWED_USERS, TELEGRAM_HOME_CHANNEL, and
KARAKEEP_API_KEY as systemd-style environment assignments. Apply the NixOS
closure again after enrolling the file so the Hermes module copies it into the
service-owned .env; then remove any temporary plaintext input used by the
no-echo SOPS stream.

The Telegram bot is polling-only and defaults to deny; never enable the global
allow-all setting. Karakeep runs as a pinned, Nix-extracted MCP program and
receives its key only through Hermes's runtime secret scope. Hermes memory,
embeddings, Hindsight, and a separate semantic retrieval layer remain disabled.
Karakeep full-text search is the only initial knowledge-retrieval path.

## Off-site host backups

Each stateful host declares its Restic paths and retention policy in Nix. The
backup unit remains condition-gated until three root-only files exist:

- /var/lib/backup-bootstrap/repository: one repository or host-specific prefix
- /var/lib/backup-bootstrap/password: the repository encryption password
- /var/lib/backup-bootstrap/environment: systemd EnvironmentFile entries for
  the least-privilege object-store writer credential

Provision these files through a no-echo SOPS enrollment stream after the
host's stable SSH/age identity is known. Never pass values as command arguments
or write plaintext into the repository. The operator must initialize an empty
repository explicitly, run the first backup, and perform a restore into an
isolated temporary host before enabling a production service.

The declarative timer runs daily with randomized delay and retains 14 daily,
8 weekly, 12 monthly, and 3 yearly snapshots. Provider snapshots and Hetzner
server backups are secondary recovery aids; they do not replace the encrypted
off-site Restic copy.

## Stalwart directory enrollment

The mail server configuration, listeners, relay routing, TLS, firewall, and
backup policy are declarative. Stalwart 0.15 remains pinned because the current
NixOS module is not compatible with 0.16; its legacy principal API cannot
safely reconcile deletions without risking mail-state detachment. Domain and
account bootstrap is consequently a documented temporary manual exception.
Create directory objects only after an isolated restore succeeds, make changes
additively, and take an encrypted backup after each accepted change. Passwords
and application-password values remain exclusively in the password manager and
Stalwart state. The exception expires when the supported declarative apply
workflow can be deployed with the NixOS module.

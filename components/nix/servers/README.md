# Declarative service hosts

The Hermes, Home Assistant, and mail-edge hosts are NixOS closures built from
this repository. OpenStack images are promoted only from a clean, signed Git
revision; the Hetzner host is installed with the pinned nixos-anywhere input.
The operator account authenticates only with the pinned SSH key and has
passwordless sudo because service hosts intentionally have no login password.

Use the no-echo enrollment app for every declared host profile:

```console
nix run .#enroll-service-host-secrets -- SSH_TARGET PROFILE [R2_ENDPOINT]
```

It validates values in memory and streams root-only mode-0400 files through
SSH standard input. It does not put a credential in an argument, local file,
Nix store path, or repository.

## Hermes enrollment

Hermes remains condition-gated until OpenAI device-code enrollment creates
/var/lib/hermes/.hermes/auth.json and a root-only
/var/lib/hermes-bootstrap/runtime.env has been enrolled. The runtime file must
contain TELEGRAM_BOT_TOKEN, TELEGRAM_ALLOWED_USERS, TELEGRAM_HOME_CHANNEL, and
KARAKEEP_API_KEY as systemd-style environment assignments. Apply the NixOS
closure again after enrolling the file so the Hermes module copies it into the
service-owned .env. Then enroll the ChatGPT/Codex subscription interactively
as the service user with `sudo -H -u hermes hermes auth add openai-codex`.

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

OpenTofu creates `fahrican-hermes-backup`,
`fahrican-home-assistant-backup`, and `fahrican-mail-edge-backup`. Use the
account endpoint exported by `services-backup-storage` and the matching bucket
only; issue an independent Object Read & Write R2 S3 key for each host so
Restic can back up, restore, and prune without crossing a host boundary.

Provision these files with the no-echo host enrollment app after the host is
reachable through its pinned SSH identity. Never pass values as command arguments
or write plaintext into the repository. The operator must initialize an empty
repository explicitly, run the first backup, and perform a restore into an
isolated temporary host before enabling a production service.

The declarative timer runs daily with randomized delay and retains 14 daily,
8 weekly, 12 monthly, and 3 yearly snapshots. Provider snapshots and Hetzner
server backups are secondary recovery aids; they do not replace the encrypted
off-site Restic copy.

## Host alert enrollment

The two OpenStack service hosts export node and systemd metrics on TCP 9100
only to the services subnet. A successful Restic unit writes an atomic
textfile metric; the post-activation synthetic wave alerts when either
exporter is unavailable or its last success is older than 26 hours. The
Internet-facing mail edge is instead covered by public protocol probes and its
local failure notifier; its exporter is not exposed across the Internet.

Critical units also use a local systemd `OnFailure` notifier. Enroll the
dedicated infrastructure bot token and chat identifier as mode-0400 files at
`/var/lib/monitoring-bootstrap/bot-token` and
`/var/lib/monitoring-bootstrap/chat-id`. Stream them from the password manager
through the encrypted SSH transport; do not put either value in an SSH command,
Nix option, shell history, or temporary file. The notifier supplies the token
to curl through standard input, so it is absent from the process list.

Hermes additionally needs its conversation bot runtime environment and OAuth
state. Mail needs Stalwart/Resend bootstrap files. Those service-specific
credentials must not reuse the infrastructure or media bots.

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

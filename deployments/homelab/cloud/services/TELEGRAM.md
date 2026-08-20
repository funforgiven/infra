# Telegram bot bootstrap

Bot identity creation and token rotation are the only BotFather exceptions.
All public metadata and private target-selection rules live in
`../telegram-bots.yaml`; `reconcile-services-telegram` applies them and writes
discovered numeric IDs directly to SOPS.

## Create the identities

Open Telegram's verified `@BotFather` account. Run `/newbot` twice and
enter these exact pairs:

| Role | BotFather name | Globally unique username |
| --- | --- | --- |
| Infrastructure alerts | `Fahrican Infra Alerts` | `fahrican_infra_alerts_bot` |
| Hermes conversation | `Fahrican Hermes` | `fahrican_hermes_bot` |

If a username is unavailable, stop and change the public username in
`../telegram-bots.yaml` in a reviewed commit before creating that bot. Do not
silently use a BotFather suggestion, because the reconciler intentionally
rejects identity drift.

For each returned token, place only the token in its matching ignored mode-0600
intake file. Do not paste tokens into a shell command or this document:

- `INFRA_TELEGRAM_BOT_TOKEN.key`
- `HERMES_TELEGRAM_BOT_TOKEN.key`

In `/mybots` → bot → Bot Settings, configure:

| Bot | Allow Groups? | Group Privacy? |
| --- | --- | --- |
| `@fahrican_infra_alerts_bot` | Enabled | Enabled |
| `@fahrican_hermes_bot` | Disabled | Enabled/default |

Do not add commands, descriptions, short descriptions, or an avatar manually.
The pinned reconciler applies the exact Git-declared name, description, short
description, and empty command menu through the supported Bot API. Version one
deliberately has no avatar asset.

## Create the private targets

Create one private Telegram group named exactly `Fahrican Infra Alerts` and add
`@fahrican_infra_alerts_bot`. The bot needs permission to send messages but
does not need administrator rights. Never convert the group to public and do
not add unrelated bots. Hermes uses a direct private conversation, not the
alerts group.

Enroll each token with the no-echo tool. Then, with no extra messages between
these actions and reconciliation:

1. Send exactly `/activate` in `Fahrican Infra Alerts`.
2. Send exactly `/activate` in the direct chat with `@fahrican_hermes_bot`.
3. Run `nix run .#reconcile-services-telegram -- apply`.

Group privacy still delivers the explicit command. The reconciler requires
exactly one matching update per bot, validates the expected username, chat
type, and group title, applies metadata, encrypts the alert group ID plus the
Hermes private chat/user IDs into their routed SOPS documents, and acknowledges
the consumed updates. It prints none of those values. If multiple matching
updates exist, send no more commands; acknowledge or inspect the ambiguity
through the operator tooling before retrying.

To move a bot to a new private target later, create exactly one fresh matching
`/activate` update and run the reconciler with `apply --rediscover`. This is an
explicit rotation operation because it replaces encrypted routing state.

# Telegram setup

Telegram bot names, descriptions, commands, and private destinations are
declared in [`../telegram-bots.yaml`](../telegram-bots.yaml). BotFather is used
only to create a bot or rotate its token.

## Create the bot

Open Telegram's verified `@BotFather` account and run `/newbot`:

| Use | Name | Username |
| --- | --- | --- |
| Infrastructure alerts | `Fahrican Infra Alerts` | `fahrican_infra_alerts_bot` |

If a username is unavailable, update `telegram-bots.yaml` before choosing a
different one.

Store the returned token in the ignored, mode-`0600`
`INFRA_TELEGRAM_BOT_TOKEN.key` intake file. Put only the token in the file; do
not pass it on a command line.

In `/mybots` → bot → Bot Settings, allow the bot in groups with group
privacy enabled. The reconciler sets the remaining public metadata and clears
the command menu.

## Enroll the alert group

1. Create a private group named `Fahrican Infra Alerts` and add
   `@fahrican_infra_alerts_bot`. It needs permission to send messages, not
   administrator access.
2. Enroll the token with the no-echo credential tool described in
   [`ACTIVATION.md`](ACTIVATION.md).
3. Send `/activate` once in the alerts group. Do not send other messages before
   reconciliation.
4. Run:

   ```bash
   nix run .#reconcile-services-telegram -- apply
   ```

The command verifies the bot and destination, applies the declared metadata,
and stores the discovered numeric group ID in a SOPS-encrypted credential
without printing it.

To move the bot later, send one new `/activate` message in the replacement
group and run:

```bash
nix run .#reconcile-services-telegram -- apply --rediscover
```

If more than one matching update exists, inspect or acknowledge the extra
updates with the reconciliation tool before retrying.

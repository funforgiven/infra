# Discord music with Muse

The Git-declared Discord music workload is
[Muse 2.11.7](https://github.com/museofficial/muse/releases/tag/v2.11.7) with
the `yt-dlp` 2026.8.19 refresh. The complete immutable image reference is:

```text
ghcr.io/museofficial/muse:2.11.7-yt-dlp-2026.8.19@sha256:ffe4274041ff82d1ed0893bc299da4ec3afb82df1aee9c4e5e10eb980a4f38f7
```

The `discord-music` Deployment has one replica in the `media` namespace and
uses `Recreate` so two bot sessions never compete for the same Discord identity
or SQLite database. Its database, guild configuration, and favorites live on
the 5 GiB `rbd1` `discord-music-data` PVC. The 2 GB media cache uses a bounded
3 GiB ephemeral volume and is discarded when the pod is replaced; it is an
optimization, not recovery data. It has no Service, ingress, or inbound public
endpoint. The workload is not usable until both credentials have been enrolled,
the runtime Secret has been delivered, and the application owner has installed
it in the intended guild using an account with **Manage Server**.

This profile enables YouTube URLs and search. Muse's optional Spotify URL
conversion is not enabled: `SPOTIFY_CLIENT_ID` and `SPOTIFY_CLIENT_SECRET` are
not part of the runtime contract. Adding them requires a separate reviewed
credential and deployment change.

## Discord voice compatibility

Discord has required DAVE end-to-end encryption support for regular voice calls
since March 2026; a client without DAVE can no longer join. This is a deployment
gate, not optional hardening. The selected Muse release pins
`@discordjs/voice` `0.19.2`, which includes DAVE support, and its lock file
resolves the DAVE implementation `@snazzah/davey` `0.1.11`. See Discord's
[DAVE voice requirements](https://docs.discord.com/developers/topics/voice-connections#end-to-end-encryption-dave-protocol)
and the
[`@discordjs/voice` changelog](https://github.com/discordjs/discord.js/blob/main/packages/voice/CHANGELOG.md).

Do not accept an image update that removes DAVE support or silently changes the
voice dependency. The REST readiness probe does not test DAVE negotiation, so
the live `/play` qualification below remains mandatory after every Muse image
or voice-library change.

## YouTube policy and reliability boundary

Muse uses the YouTube Data API for search and metadata, then uses `yt-dlp` to
resolve and extract playable audio. The API key does not authorize that
extraction. This behavior is not an official YouTube playback path and may
conflict with the [YouTube Terms of Service](https://www.youtube.com/t/terms)
and the
[YouTube API Services Developer Policies](https://developers.google.com/youtube/terms/developer-policies),
including their restrictions on downloading or caching audiovisual content,
separating audio, background playback, and retrieving content outside the
YouTube API Services. Operate it only for content you are entitled to play and
only after accepting the policy, account, and legal risk.

Extraction is inherently fragile. YouTube can change signatures, require a new
JavaScript challenge implementation, rate-limit the cluster egress address, or
gate media by account, age, region, or bot-detection checks. A healthy pod and a
valid Data API key therefore do not guarantee that a track will play. A pinned
refresh image makes changes reviewable, but it also means extractor fixes
require a reviewed image update.

This deployment deliberately has **no cookie support**. Do not export, enroll,
mount, or add a runtime contract for browser or YouTube account cookies, and do
not set `YT_DLP_COOKIES_PATH`. Login-gated and age-restricted media is expected
to fail. Cookies would be reusable account credentials and would not remove the
policy or reliability risk.

## Create the Discord application

Use the [Discord Developer Portal](https://discord.com/developers/applications)
while signed in as the account that will own this private bot:

1. Create a new application named `Muse` or another unambiguous server-local
   name. Record the application ID as non-secret inventory.
2. On **Bot**, create the bot user if Discord has not already done so. Keep a
   private, single-server bot non-public when the portal offers that setting.
3. Leave all **Privileged Gateway Intents** disabled: **Presence Intent**,
   **Server Members Intent**, and **Message Content Intent**. Muse 2.11.7 uses
   guild, reaction, and voice-state events plus application commands; none is a
   privileged intent.
4. On **Installation**, support **Guild Install** only. Do not enable User
   Install. Set **Install Link** to **None**: Discord does not allow a private
   application to have a default authorization link.
5. Open **OAuth2** > **URL Generator**. Select the `applications.commands` and
   `bot` scopes and, if Discord shows an integration-type choice, select
   **Guild Install**. Give the bot only these permissions:

   - **View Channels** (`VIEW_CHANNEL`);
   - **Send Messages**;
   - **Embed Links**;
   - **Connect**;
   - **Speak**;
   - **Use Voice Activity** (`USE_VAD`).

   The equivalent permission integer is `36719616`. Do not grant
   **Administrator**, moderation, role-management, message-history, member, or
   presence permissions.
6. Retain the generated OAuth2 authorization URL for the eventual owner-only
   install, but do not post it publicly. Because the bot is private, the
   application owner must authorize it while using an account that also has
   **Manage Server** in the target guild.
7. Return to **Bot**, select **Reset Token**, and copy the new bot token directly
   into its local intake file. Discord shows it only once. Never put it in a
   shell argument, environment file, clipboard manager, tracked file, chat, or
   log.

After installation, narrow the bot role with channel overrides so it can view
and send only in the intended command channel and can connect and speak only in
the intended voice channels. Channel overrides must retain the six permissions
above where Muse is expected to work.

## Create the YouTube API key

In the [Google Cloud Console](https://console.cloud.google.com/):

1. Create or select a project dedicated to this bot.
2. Enable **YouTube Data API v3**.
3. Create an API key under **APIs & Services** > **Credentials**.
4. Under **API restrictions**, restrict the key to **YouTube Data API v3**.
   Apply a suitable application restriction as well if the services cluster has
   a stable, known egress address.
5. Copy the key directly into its local intake file. This key is for API
   metadata and quota attribution; it is not a YouTube login, playback license,
   or cookie.

Do not create OAuth user credentials or supply a Google account session to
Muse. Monitor quota in the dedicated project; exhausted or revoked quota makes
search and metadata requests fail even when extraction would otherwise work.

## Enroll the credentials

Create a private intake directory outside Git. The two accepted file names are:

| File | Exact contents |
| --- | --- |
| `DISCORD_MUSIC_BOT_TOKEN.key` | The Discord bot token only |
| `DISCORD_MUSIC_YOUTUBE_API_KEY.key` | The restricted YouTube Data API key only |

Each must be a regular, non-symlink file with mode `0600`, containing exactly
one non-empty line without a variable name, quotes, or trailing commentary.
For example, create the empty files before filling them with a trusted local
editor:

```sh
install -d -m 0700 /absolute/path/to/intake
touch /absolute/path/to/intake/DISCORD_MUSIC_BOT_TOKEN.key
touch /absolute/path/to/intake/DISCORD_MUSIC_YOUTUBE_API_KEY.key
chmod 0600 /absolute/path/to/intake/DISCORD_MUSIC_BOT_TOKEN.key
chmod 0600 /absolute/path/to/intake/DISCORD_MUSIC_YOUTUBE_API_KEY.key
```

Enroll both values from the repository root without putting either value in a
command argument:

```sh
nix run .#enroll-services-credential -- \
  --from-file --intake-directory /absolute/path/to/intake \
  DISCORD_MUSIC_BOT_TOKEN
nix run .#enroll-services-credential -- \
  --from-file --intake-directory /absolute/path/to/intake \
  DISCORD_MUSIC_YOUTUBE_API_KEY
```

Enrollment writes each value to the declared SOPS document as ciphertext and
truncates that intake file only after encryption succeeds. Review only the
ciphertext structure and diff statistics, commit the encrypted result, and let
the services-cluster reconciler create `discord-music-runtime` in `media`. Do
not install the bot while the Deployment is failing because either credential
is still absent.

## Install and verify

After the committed ciphertext has reconciled, verify the workload without
printing its environment or Secret:

```sh
kubectl -n media rollout status deployment/discord-music --timeout=5m
kubectl -n media get deployment discord-music
kubectl -n media logs deployment/discord-music --tail=100
```

Accept only one ready replica. The startup log must show a successful Discord
connection and command registration, with no authentication, quota, extractor,
filesystem, or voice-library error. Do not paste logs into chat; even sanitized
logs can contain guild, channel, query, or media identifiers. Readiness checks
the bot token against Discord but does not exercise YouTube extraction or voice
playback. There is intentionally no liveness probe that could restart Muse
repeatedly during a Discord outage.

Then complete the human-authorized guild setup:

1. As the application owner, open the saved URL from **OAuth2** > **URL
   Generator**, choose **Add to Server**, and select the intended server. The
   approving account must also have **Manage Server** in that guild.
2. On the authorization screen, re-check the `bot` and
   `applications.commands` scopes and the six permissions above. Reject the
   install if **Administrator** or any additional permission appears.
3. Confirm Muse appears online. Its guild-owner DM is informational and may be
   hidden by Discord privacy settings; it is not an activation secret or health
   check.
4. In the intended text channel, run `/config get`. Only a member with
   **Manage Server** can use this configuration command.
5. Join an allowed voice channel and run `/play` with a small YouTube URL or
   search for content you are authorized to play. Confirm Muse joins the same
   channel, produces audible audio, and responds in the intended text channel.
6. Run `/disconnect`, then confirm it leaves and that no second pod or bot
   session appears.
7. Confirm the bot cannot view unrelated private channels, join disallowed
   voice channels, manage roles or messages, or read message content.

A successful `/config get` verifies Discord command registration but not the
YouTube extractor. A successful `/play` is required after initial enrollment
and after every image, Discord voice-library, or extractor refresh.

## Backup and recovery

For Muse, Velero backs up only the persistent `data` volume. Before its
filesystem copy, a pod hook uses SQLite's online backup API to create
`/data/recovery/db.sqlite`, verifies that copy with `PRAGMA quick_check`, sets
mode `0600`, and replaces the prior recovery copy atomically. A failed hook or
integrity check fails the backup. The live database remains available while the
consistent recovery copy is created.

The `/data/cache` and 1 GiB `/tmp` mounts are bounded ephemeral volumes and are
not backed up. A restored cache starts empty and repopulates on demand; it must
never be treated as application data or a recovery source.

Qualify a recovery point through the
[isolated media restore procedure](../16-backup-policy/README.md#isolated-media-restore).
Keep the restored namespace deny-all and do not allow a restored Muse pod to
connect with the production token: two active sessions would compete for one
bot identity. Verify the restored `/data/recovery/db.sqlite` read-only with
SQLite's integrity check before accepting it. For live recovery, stop the sole
Muse replica before replacing database state, use the verified recovery copy
rather than the concurrently changing live database file, and bring back
exactly one replica. Do not copy over an open SQLite database.

## Rotate or revoke credentials

Never edit `discord-music-runtime` directly. Before a planned rotation, record
its current resource version without reading any Secret data:

```sh
kubectl -n media get secret discord-music-runtime \
  -o jsonpath='{.metadata.resourceVersion}{"\n"}'
```

Rotate through the same intake and SOPS path, then wait for the
services-cluster reconciler to change that resource version. Restart the
Deployment only after it changes so the new environment value is loaded:

```sh
kubectl -n media rollout restart deployment/discord-music
kubectl -n media rollout status deployment/discord-music --timeout=5m
```

For the Discord token, **Reset Token** in the Developer Portal invalidates the
old token immediately. Expect downtime while enrolling and reconciling
`DISCORD_MUSIC_BOT_TOKEN`. Restart Muse only after the Secret has received the
new value, then repeat `/config get` and the voice playback check. A token reset
does not require reinstalling the application in the guild because the bot
identity and application ID stay the same.

For the YouTube API key, create and restrict a replacement first. Enroll and
reconcile `DISCORD_MUSIC_YOUTUBE_API_KEY`, restart and qualify playback, then
disable and delete the old key in Google Cloud. If compromise is suspected,
revoke the exposed key immediately and accept the outage rather than waiting
for a no-downtime handoff.

SOPS re-encryption alone does not rotate either provider credential. After a
suspected disclosure, revoke the provider-side value, enroll its replacement,
and remember that old ciphertext may remain in Git history even though it
cannot be used without an authorized age identity.

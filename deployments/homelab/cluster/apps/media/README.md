# Music library and Discord music

SFTPGo is a temporary upload inbox, Beets owns the library, Navidrome serves
only files accepted by Beets, AudioMuse analyses the library for Navidrome, and
Muse plays YouTube audio in Discord.

## Add music

1. Download complete albums on the workstation (Streamrip may use the local
   Deezer configuration; provider and payment credentials never reach a
   workload).
2. Upload them as received at <https://upload.fahrican.com/web/client> (ZITADEL
   login; the account has no local password or other protocol).
3. Beets imports once the inbox has been quiet for two minutes, using confident
   MusicBrainz/Deezer matches without prompting. Listen at
   <https://music.fahrican.com> or any OpenSubsonic client.

For a large batch, stage complete album directories outside `inbox` and rename
them in after validation: the quiet period cannot detect a paused upload. Use
Picard for albums that need a manual MusicBrainz choice, then upload again.

## Library policy

- Numeric Deezer IDs never go into MusicBrainz UUID fields; provider IDs are
  written explicitly to FLAC tags (`normalize-provider-ids.py`).
- The library is studio-only: recordings marked live by MusicBrainz or by
  concert markers in titles move to quarantine; for Ado, remixes, piano,
  instrumental, a cappella, speed and stripped versions do too
  (`quarantine-live.py`). A title merely containing "live" stays.
- Duplicates (artist + album title), unmatched, unsupported and leftover files
  move to a timestamped `quarantine` directory that neither SFTPGo nor
  Navidrome can see. Nothing deletes quarantine automatically; review it.
- Refreshing an existing album is a reviewed, manual operation: the inbox never
  overwrites a release because another copy arrived.
- The daily LastGenre cleanup only normalizes existing genres and runs only
  while `verify-lastgenre-offline.py` proves it makes no Last.fm requests.

## Accounts

Create the first Navidrome administrator on its one-time setup page. The
`audiomuse` service account is created on the next Navidrome pod start after
that (the init skips it while no admin exists, so the setup page stays
reachable). Last.fm and ListenBrainz are authorized by each user in Navidrome.

Browser sessions for Navidrome and AudioMuse use ZITADEL refresh tokens with
30-day cookies. SFTPGo reloads its upload account from `sftpgo-initial-data.json`
on every start; its local `admin` (emergency inspection only) is created once
from `SFTPGO_ADMIN_PASSWORD`, so rotating that value later needs a password
change in SFTPGo too.

## AudioMuse database

`audiomuse-db` is a CloudNativePG cluster bootstrapped by importing the legacy
`audiomuse-postgres` StatefulSet, which remains only until the cutover is
verified. AudioMuse's database is recomputable analysis data; its CNPG volumes
are covered by the daily volume snapshot schedule.

AudioMuse 3.4.0 can persist its `TASK_STATUS_LIVE`/`TASK_STATUS_TERMINAL`
tuples in `app_config` in a form it cannot read back, producing invalid queue
SQL after a restart. If that recurs, confirm the traceback and the exact rows
`('NEW', 'RUNNING')` and `('SUCCESS', 'FAIL', 'REVOKED')`, delete only those two
overrides in a transaction, and require a healthy `/api/health`. Never clear
`app_config` or task-status data.

## Discord music (Muse)

One replica with `Recreate`: two pods would compete for one bot identity and
SQLite database. The cache is disposable; only `/data` is backed up, through a
pre-backup hook (`sqlite-backup.py`) that writes a verified online copy to
`/data/recovery/db.sqlite`. Restore from that copy with Muse stopped, never
over an open database, and never let a restored pod run with the production
token.

- **DAVE is mandatory.** Discord voice requires DAVE end-to-end encryption;
  reject an image that drops it from `@discordjs/voice`. Readiness only checks
  the token, so run a real `/play` after every image or voice-library change.
- **YouTube boundary.** Search uses the Data API key; playback uses `yt-dlp`,
  which may conflict with YouTube's terms and breaks when YouTube changes.
  There is deliberately no cookie support: login- and age-gated media fails.
- **Discord application.** Private, guild-install only, no privileged intents,
  scopes `bot applications.commands`, permissions View Channels, Send
  Messages, Embed Links, Connect, Speak, Use Voice Activity (`36719616`), then
  narrow with channel overrides. The installer needs **Manage Server**.
- **Credentials.** Enroll `DISCORD_MUSIC_BOT_TOKEN` and
  `DISCORD_MUSIC_YOUTUBE_API_KEY` (API-restricted to YouTube Data API v3)
  with `nix run .#enroll-services-credential -- --from-file ...`, then
  `nix run .#render-cluster-credentials`. After the Secret changes, restart
  the Deployment. Resetting the Discord token invalidates the old one
  immediately; for the YouTube key, create the replacement first. SOPS
  re-encryption is not a rotation.

## Verify a change

Upload a small test album, confirm Beets tags and moves it and Navidrome scans
it, upload it again and confirm the duplicate is quarantined. Backups and the
isolated media restore are owned by `infrastructure/backups/`.

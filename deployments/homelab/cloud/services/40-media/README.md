# Purchased music workflow

The initial music workflow deliberately separates discovery, payment, import,
and playback:

1. Save Bandcamp, OTOTOY, label, and artist release pages in Karakeep with the
   music/wanted tag. Hermes can summarize the queue and send reminders through
   the dedicated conversation bot, but cannot purchase anything.
2. Complete every checkout manually. Payment credentials stay in the personal
   password manager and are never provided to Hermes or a workload.
3. Upload one album directory at a time through the SFTPGo WebClient at
   https://inbox.fahrican.com/web/client.
4. The pinned beets importer uses MusicBrainz, Japanese-first aliases,
   Chromaprint, and Cover Art Archive metadata. Only strong quiet-mode matches
   move into the Navidrome library. Ambiguous, duplicate, malformed, or failed
   imports move to quarantine and trigger a Telegram message.
5. Review quarantine interactively with the same pinned beets package; never
   accept a low-confidence match unattended.

Navidrome is available at https://music.fahrican.com. Last.fm server keys are
in the media-runtime SOPS Secret. Last.fm and ListenBrainz scrobbling are linked
per Navidrome user through their upstream interactive authorization flows.

## Activation gates

- Create media-runtime as SOPS ciphertext with independent high-entropy
  SFTPGo admin/user passwords, a Navidrome password-encryption key, Last.fm API
  key/secret, and the dedicated media Telegram bot token/chat ID.
- Build and publish media-importer only from a clean signed commit using
  nix run .#promote-media-importer. Replace the all-zero digest with the
  registry-returned digest in a second signed commit.
- Confirm the Manila RWX and Cinder RWO qualification, Velero object-store
  location, daily and weekly schedules, and an isolated restore of all four
  PVCs.
- Resume services-observability, services-backup-controller,
  services-backup-policy, and then services-media in that order.
- Create the first Navidrome admin through its one-time setup page, link
  scrobbling, run a test purchase import, inspect the tags, and restore the
  result into an isolated namespace before treating the workflow as production.

SFTPGo configuration and accounts are recreated from Git plus runtime secrets
on every pod start. WebAdmin is inspection-only; accepted configuration changes
must be represented in the bootstrap data before they are retained.

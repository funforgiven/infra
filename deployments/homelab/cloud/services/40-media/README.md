# Purchased music workflow

The initial music workflow is intentionally direct:

1. Purchase and download an album manually from OTOTOY, Bandcamp, or another
   store. Payment credentials stay in the personal password manager and are
   never provided to Hermes or a workload.
2. Sign in to the SFTPGo WebClient at
   https://inbox.fahrican.com/web/client as `music-library` and upload the album
   files or directory as received.
3. SFTPGo writes directly to the shared `media-library` volume. Navidrome
   mounts its `library` directory read-only at `/music` and scans it for
   changes.
4. Listen through Navidrome at https://music.fahrican.com or through Symfonium
   using Navidrome as the server.

There is no deployed importer, release watcher, automatic tagging, automatic
directory organization, or media Telegram bot. Picard is an optional desktop
repair tool only: if an album's embedded metadata looks wrong in Navidrome,
fix that album manually and upload the corrected files again.

Navidrome is available at https://music.fahrican.com. Last.fm server keys are
in the media-runtime SOPS Secret. Last.fm and ListenBrainz scrobbling are linked
per Navidrome user through their upstream interactive authorization flows.

## Activation gates

- Enroll the media contract into the central services bootstrap SOPS Secret;
  the reconciler derives `media-runtime` without persisting plaintext.
- Confirm the Manila RWX and Cinder RWO qualification, Velero object-store
  location, daily and weekly schedules, and an isolated restore of all three
  PVCs.
- Resume services-observability, services-backup-controller,
  services-backup-policy, and then services-media in that order.
- Create the first Navidrome admin through its one-time setup page, link
  scrobbling, upload a test album through SFTPGo, confirm that Navidrome scans
  it, and restore the result into an isolated namespace before treating the
  workflow as production.

SFTPGo configuration and accounts are recreated from Git plus runtime secrets
on every pod start. WebAdmin is inspection-only; accepted configuration changes
must be represented in the bootstrap data before they are retained.

# Purchased music workflow

SFTPGo is a temporary upload inbox; Beets owns the permanent library:

1. Purchase and download an album manually from OTOTOY, Bandcamp, or another
   store. Payment credentials stay in the personal password manager and are
   never provided to Hermes or a workload.
2. Sign in to the SFTPGo WebClient at
   https://upload.fahrican.com/web/client with ZITADEL and upload the album files
   or directory as received. The predeclared upload account is matched from the
   identity token's verified `email` claim and has no local password or file
   transfer protocol access.
3. SFTPGo publishes completed files atomically into the `inbox` directory on
   the shared `media-library` volume. The Beets CronJob runs every five minutes
   and waits until the whole inbox has been unchanged for at least 15 minutes,
   so a multi-track album is considered as a unit.
4. Beets accepts only confident MusicBrainz matches without prompting. It
   writes the matched tags and artwork, skips duplicates already represented
   in its persistent catalog, and moves accepted audio into its standard
   artist/album/track hierarchy under `library`.
5. Navidrome mounts only `library` read-only at `/music` and scans it every five
   minutes. Listen at https://music.fahrican.com or through Symfonium
   using Navidrome as the server.

After a successful import pass, anything remaining in `inbox` is moved into a
timestamped directory under `quarantine`. This includes duplicate uploads,
matches that were not confident enough to accept, unsupported files, and
extras that Beets did not associate with an album. Quarantine is outside the
SFTPGo home and the Navidrome library: it preserves data for explicit operator
review without making the upload service permanent storage or exposing rejected
media to listeners. A failed Beets process leaves the inbox in place for the
next run. The first run catalogs the pre-existing `library` as-is before it
processes new uploads, so the database begins with the direct-upload collection.

The WebClient trusts the rightmost `X-Forwarded-For` address only when the
direct peer is in the services cluster's `172.16.0.0/13` Calico pool. The media
NetworkPolicy independently limits SFTPGo HTTP ingress to the Envoy Gateway
namespace. This gives OIDC and CSRF validation a stable browser address when
successive requests traverse different Envoy replicas without accepting proxy
headers from other namespaces.

There is no release watcher or media Telegram bot. Picard remains an optional
desktop repair tool for releases that Beets quarantines or that need a manual
MusicBrainz choice; upload the corrected album again after repair.

Navidrome is available at https://music.fahrican.com. Last.fm server keys are
in the media-runtime SOPS Secret. Last.fm and ListenBrainz scrobbling are linked
per Navidrome user through their upstream interactive authorization flows.

## Activation gates

- Enroll the media contract into the central services bootstrap SOPS Secret;
  the reconciler combines it in memory with the Git-managed ZITADEL application
  output to derive `media-runtime` without persisting plaintext.
- Confirm the Manila RWX and Cinder RWO qualification, Velero object-store
  location, daily and weekly schedules, and an isolated restore of all four
  PVCs, including the Beets catalog and import marker in `beets-data`.
- Resume services-observability, services-backup-controller,
  services-backup-policy, and then services-media in that order.
- Create the first Navidrome admin through its one-time setup page and link
  scrobbling. Upload a test album through SFTPGo, wait for the quiet period,
  confirm the Beets job moved and tagged it and Navidrome scanned it, then
  upload it again and confirm the duplicate is quarantined. Restore the
  library, Beets catalog, and quarantine into an isolated namespace before
  treating the workflow as production.

SFTPGo configuration and accounts are recreated from Git plus runtime secrets
on every pod start. The local administrator login remains an emergency and
inspection path; accepted configuration changes must be represented in the
bootstrap data before they are retained. The public user surface accepts
ZITADEL OIDC only: the native WebClient login form, user token endpoint, and
user API-key login are disabled globally, while password, API-key, public-key,
and TLS-certificate changes are disabled for the predeclared upload account.

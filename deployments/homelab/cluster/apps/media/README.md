# Music library workflow

SFTPGo is a temporary upload inbox, Beets owns the library, and Navidrome serves
only files accepted by Beets.

## Add music

1. Download the album on the workstation. Streamrip can use the local Deezer
   account configuration; keep provider and payment credentials outside this
   repository and never provide them to a workload. Keep full albums together.
2. Sign in to <https://upload.fahrican.com/web/client> with ZITADEL and upload
   the album as received. The upload account has no local password or other file
   transfer access.
3. SFTPGo writes files atomically. Beets waits until the complete inbox has
   been unchanged for two minutes, then imports confident MusicBrainz matches
   without prompting.
4. Listen at <https://music.fahrican.com> or through an OpenSubsonic client such
   as Symfonium.

Beets prefers MusicBrainz metadata with Deezer as an additional metadata source,
writes canonical tags and artwork, and moves accepted tracks to the
artist/album/track library. Duplicate checks use the artist and album title;
different versions sharing those names need explicit review. Release titles
and edition disambiguation are retained, and rejected copies remain in
quarantine instead of being discarded by a release-group rule.
MusicBrainz genres and linked service IDs are imported when available, and
barcode and track count help constrain metadata searches.
Deezer-only matches retain their provider IDs; numeric identifiers are removed
from MusicBrainz UUID fields rather than presented as unverified MusicBrainz
matches. The provider IDs are also written explicitly into FLAC tags.
Missing embedded artwork is filled from the album cover; existing embedded
pictures are preserved, and the external cover is kept for Navidrome.
It calculates track and album ReplayGain metadata without re-encoding audio.
Navidrome mounts that library read-only and scans once per minute.

The listening library is studio-only. After import, recordings explicitly
identified as live by MusicBrainz release types or concert-version markers in
album/track titles move out of the catalog and into retained quarantine. This
also handles live bonus tracks within an otherwise studio release. A studio
song title merely containing the word "live" does not trigger this rule.
Ado's intake also keeps standard vocal versions: explicitly marked remixes,
piano versions, instrumentals, a cappella, speed variants, and stripped versions
go to quarantine. Other artists' studio bonus tracks retain their release's
track list.

Rejected, duplicate, unsupported, and unmatched files move to a timestamped
directory under `quarantine`. Quarantine is not visible to SFTPGo or Navidrome
and is retained until reviewed. Inspect and resolve quarantine explicitly; no
scheduled job deletes unmatched music or uncertain duplicates. A failed Beets
run leaves the inbox for the next attempt.

For a large batch, prepare complete album directories in a staging directory
outside `inbox`, then rename them into `inbox` after validation. The two-minute
quiet period cannot guarantee completeness if an upload pauses for longer.
Refreshing an existing album is a reviewed operation: preserve its audio when
decoded PCM matches, merge missing source metadata, and compare artwork before
replacing it. The automatic inbox never overwrites an existing release merely
because another copy arrives.

Use Picard for an album that needs a manual MusicBrainz choice, then upload the
corrected files again. There is no automatic release watcher or purchasing bot.

## Accounts and scrobbling

Navidrome and AudioMuse browser sessions use ZITADEL refresh tokens and
30-day cookies, refreshed on use. ZITADEL password and MFA checks also remain
valid for 30 days. Existing sessions need one new login to receive refresh tokens.

Create the first Navidrome administrator through its one-time setup page.
Last.fm and ListenBrainz authorization is performed separately by each
Navidrome user. Provider tokens remain in Navidrome state and its encrypted
backups.

SFTPGo rebuilds its declared configuration and upload account from the runtime
Secret at pod start. The local administrator account is only for emergency
inspection. Browser access uses ZITADEL OIDC; local user passwords, user API
keys, and the native login form are disabled.

## Verify a change

Before accepting media data, require successful backups and an isolated restore
of the library, Beets catalog, Navidrome state, and quarantine PVCs.

For an application or import-policy change:

1. Upload a small test album.
2. Confirm Beets moves and tags it after the quiet period.
3. Confirm Navidrome scans it.
4. Upload it again and confirm the duplicate is quarantined.
5. Restore the relevant PVCs into an isolated namespace and verify the catalog
   and representative audio.

## AudioMuse startup recovery

The pinned AudioMuse 3.4.0 setup bootstrap can persist its internal
`TASK_STATUS_LIVE` and `TASK_STATUS_TERMINAL` tuples in `app_config`. Its
`SetupManager.cast_value` does not deserialize tuples. After a restart this
can generate invalid queue SQL by treating each character as a status.

During the 2026-09-09 worker replacement, the affected rows contained exactly
`('NEW', 'RUNNING')` and `('SUCCESS', 'FAIL', 'REVOKED')`. Preserving those rows
and removing only these two malformed overrides restored the pinned code's
defaults. No task, music, media-server or user configuration rows were changed.
The frontend became Ready without an image upgrade or database restore.

If this specific failure recurs, verify the image, traceback and both exact
values first. Preserve the rows, remove only those verified internal overrides
in a transaction, and require a successful `/api/health` response. Do not clear
`app_config` or change task-status data. A setup operation that writes all
defaults may recreate the overrides; inspect the upstream tuple serialization
before treating an upgrade as a fix.

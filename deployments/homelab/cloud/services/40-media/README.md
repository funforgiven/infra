# Purchased music workflow

SFTPGo is a temporary upload inbox, Beets owns the library, and Navidrome serves
only files accepted by Beets.

## Add music

1. Purchase and download the album manually. Store and payment credentials stay
   in the password manager and are never provided to a workload.
2. Sign in to <https://upload.fahrican.com/web/client> with ZITADEL and upload
   the album as received. The upload account has no local password or other file
   transfer access.
3. SFTPGo writes uploads atomically. Beets waits until the complete inbox has
   been unchanged for two minutes, then imports confident MusicBrainz matches
   without prompting.
4. Listen at <https://music.fahrican.com> or through an OpenSubsonic client such
   as Symfonium.

Beets uses the MusicBrainz release-group ID as album identity, writes canonical
tags and artwork, and moves accepted tracks to the artist/album/track library.
It calculates track and album ReplayGain metadata without re-encoding audio.
Navidrome mounts that library read-only and scans once per minute.

Rejected, duplicate, unsupported, and unmatched files move to a timestamped
directory under `quarantine`. Quarantine is not visible to SFTPGo or Navidrome
and is retained for 24 hours. Manually named review directories are kept. A
failed Beets run leaves the inbox for the next attempt.

Use Picard for an album that needs a manual MusicBrainz choice, then upload the
corrected files again. There is no automatic release watcher or purchasing bot.

## Accounts and scrobbling

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

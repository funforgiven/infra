#!/bin/sh
set -eu
umask 002

media_root=${BEETS_MEDIA_ROOT:-/media}
state=${BEETS_STATE_ROOT:-/state}
beet=${BEETS_EXECUTABLE:-/lsiopy/bin/beet}
inbox=$media_root/inbox
library=$media_root/library
quarantine=$media_root/quarantine

mkdir -p "$inbox" "$library" "$quarantine" "$state/cache"

# Unmatched music and uncertain duplicates need review. Keep them until an
# operator resolves them instead of deleting music files after one day.

# The pre-Beets library was written directly by SFTPGo. Catalog it once without
# changing its tags so duplicate detection also covers music from that workflow.
if [ ! -e "$state/library-cataloged" ]; then
  "$beet" import --noautotag "$library"
  touch "$state/library-cataloged"
fi

# Preserve the matched release's title and edition disambiguation. A release
# group title alone cannot distinguish expanded editions or live recordings.

# ReplayGain was enabled after the original library had already been cataloged.
# Re-analyze the existing catalog once so every album gets coherent track and
# album gain/peak values and every standalone track gets track values. The
# ffmpeg backend writes metadata tags only; it never re-encodes the audio. Force
# this versioned migration so database-only or partial values cannot cause an
# on-disk file to be skipped. A failed pass leaves the marker absent and is
# safely retried by the next CronJob run.
replaygain_backfill="$state/replaygain-album-track-v1"
if [ ! -e "$replaygain_backfill" ]; then
  "$beet" replaygain -a -f -w
  "$beet" replaygain -f -w "singleton:true"
  touch "$replaygain_backfill"
fi

# Normalize only genres already present in the library. The acceptance script
# replaces LastGenre's network client with a hard failure first, proving this
# exact cleanup path makes zero Last.fm requests in the deployed Beets image.
lastgenre_maintenance="$state/lastgenre-offline-maintenance"
if [ ! -e "$lastgenre_maintenance" ] || \
  find "$lastgenre_maintenance" -mmin +1440 -print -quit | grep -q .; then
  /opt/beets/verify-lastgenre-offline.py
  "$beet" lastgenre 'genre::.'
  touch "$lastgenre_maintenance"
fi

if ! find "$inbox" -mindepth 1 -print -quit | grep -q .; then
  printf '%s\n' "Beets inbox is empty"
  exit 0
fi

# SFTPGo publishes each file atomically. This additional quiet period keeps a
# directory containing a multi-file album together while its tracks arrive.
if find "$inbox" -mindepth 1 -mmin -2 -print -quit | grep -q .; then
  printf '%s\n' "Beets inbox changed within the last 2 minutes; deferring import"
  exit 0
fi

if find "$inbox" -type f -print -quit | grep -q .; then
  "$beet" import "$inbox"
  /lsiopy/bin/python /opt/beets/normalize-provider-ids.py \
    --library "$state/library.db" --directory "$library"
  /lsiopy/bin/python /opt/beets/quarantine-live.py \
    --library "$state/library.db" --directory "$library" \
    --quarantine "$quarantine" --standard-vocals-artist Ado
fi

# Successful imports have already moved their audio into the library. Preserve
# anything Beets left behind outside SFTPGo for explicit review instead of
# silently deleting duplicates, unmatched audio, artwork, or other extras.
if find "$inbox" -mindepth 1 -print -quit | grep -q .; then
  review="$quarantine/$(date -u +%Y%m%dT%H%M%SZ)-${POD_NAME:-unknown}"
  mkdir "$review"
  for candidate in "$inbox"/* "$inbox"/.[!.]* "$inbox"/..?*; do
    [ -e "$candidate" ] || continue
    mv "$candidate" "$review/"
  done
  printf 'Moved Beets leftovers to %s\n' "$review"
fi

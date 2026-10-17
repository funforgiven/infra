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

# Keep unmatched music and uncertain duplicates for operator review.

# Normalize only genres already present in the library. The verification script
# first replaces LastGenre's network client with a hard failure, so this cleanup
# makes no Last.fm requests.
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

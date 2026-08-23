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

# The pre-Beets library was written directly by SFTPGo. Catalog it once without
# changing its tags so duplicate detection also covers music from that workflow.
if [ ! -e "$state/library-cataloged" ]; then
  "$beet" import --noautotag "$library"
  touch "$state/library-cataloged"
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

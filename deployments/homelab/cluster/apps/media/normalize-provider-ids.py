#!/usr/bin/env python3
"""Keep Deezer's numeric identifiers out of MusicBrainz UUID fields."""

import argparse
import os

from beets.library import Library
from mutagen.flac import FLAC


def numeric(value):
    return bool(value) and str(value).isascii() and str(value).isdigit()


def clear_numeric(model, fields):
    changed = False
    for field in fields:
        value = model[field]
        if isinstance(value, list):
            clean = [identifier for identifier in value if not numeric(identifier)]
        else:
            clean = "" if numeric(value) else value
        if clean != value:
            model[field] = clean
            changed = True
    return changed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library", required=True)
    parser.add_argument("--directory", required=True)
    args = parser.parse_args()
    lib = Library(args.library, directory=args.directory)
    album_fields = ("mb_albumid", "mb_albumartistid", "mb_albumartistids")
    item_fields = album_fields + (
        "mb_artistid",
        "mb_artistids",
        "mb_trackid",
        "mb_releasetrackid",
    )
    albums = set()
    corrected = 0
    for item in lib.items():
        if item.get("data_source", "").lower() != "deezer":
            continue
        if item.album_id:
            albums.add(item.album_id)
        if not clear_numeric(item, item_fields):
            continue
        # These provider fields are already retained by Beets' Deezer plugin.
        # Write them explicitly into FLACs because they are flexible database
        # fields rather than MediaFile tags in the pinned Beets version.
        item.write()
        if os.fsdecode(item.path).lower().endswith(".flac"):
            audio = FLAC(item.path)
            for field in ("deezer_album_id", "deezer_track_id"):
                identifier = item.get(field)
                if identifier:
                    audio[field.upper()] = str(identifier)
            audio.save()
        item.store()
        corrected += 1
    for album_id in albums:
        album = lib.get_album(album_id)
        if clear_numeric(album, album_fields):
            album.store(inherit=False)
    print(f"Normalized provider identifier tags on {corrected} tracks")


if __name__ == "__main__":
    main()

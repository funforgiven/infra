#!/usr/bin/env python3
"""Retain identified concert recordings outside the studio-only library."""

import argparse
import datetime
import json
import os
from pathlib import Path
import re

from beets.library import Library


LIVE_MARKER = re.compile(r"[\[(][^\])]*\blive\b|\blive\s+(?:at|in|from)\b", re.I)
AUDIO_EXTENSIONS = {".flac", ".mp3", ".m4a", ".ogg", ".opus", ".wav", ".aiff"}
ALTERNATE_MARKER = re.compile(
    r"\b(?:remix|instrumental|a\s*cappella|sped\s*up|slowed\s*down|stripped)\b"
    r"|[\[(][^\])]*\bpiano\b",
    re.I,
)


def is_live(model):
    types = model.get("albumtypes", []) or model.get("albumtype", "")
    if not isinstance(types, list):
        types = re.findall(r"[a-z]+", str(types).lower())
    return "live" in [str(value).lower() for value in types] or any(
        LIVE_MARKER.search(str(model.get(field, ""))) for field in ("album", "title")
    )


def rejection_reason(item, standard_artist):
    if is_live(item):
        return "live recording"
    artists = f"{item.artist}; {item.albumartist}"
    if standard_artist and re.search(rf"\b{re.escape(standard_artist)}\b", artists, re.I):
        if any(ALTERNATE_MARKER.search(str(item.get(field, ""))) for field in ("album", "title")):
            return "alternate studio version"
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library", required=True)
    parser.add_argument("--directory", required=True)
    parser.add_argument("--quarantine", required=True)
    parser.add_argument("--report")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--standard-vocals-artist")
    args = parser.parse_args()
    lib = Library(args.library, directory=args.directory)
    root = Path(args.directory).resolve()
    selected = [item for item in lib.items() if rejection_reason(item, args.standard_vocals_artist)]
    report = {
        "removed_tracks": len(selected),
        "albums": sorted({item.album for item in selected}),
        "items": [
            {
                "path": os.fsdecode(item.path),
                "album": item.album,
                "title": item.title,
                "reason": rejection_reason(item, args.standard_vocals_artist),
            }
            for item in selected
        ],
    }
    if selected and not args.dry_run:
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        destination = Path(args.quarantine) / f"{stamp}-live-{os.getpid()}"
        destination.mkdir(parents=True)
        selected_paths = {Path(os.fsdecode(item.path)).resolve() for item in selected}
        moves = []
        handled = set()
        try:
            for item in selected:
                path = Path(os.fsdecode(item.path)).resolve()
                if any(path == moved or moved in path.parents for moved in handled):
                    continue
                path.relative_to(root)
                assert path.is_file(), f"Catalogued live file missing: {path}"
                folder = path.parent
                audio = {p.resolve() for p in folder.rglob("*") if p.suffix.lower() in AUDIO_EXTENSIONS}
                source = folder if audio and audio <= selected_paths else path
                if source in handled:
                    continue
                target = destination / source.relative_to(root)
                target.parent.mkdir(parents=True, exist_ok=True)
                os.rename(source, target)
                moves.append((source, target))
                handled.add(source)
            with lib.transaction():
                for item in selected:
                    item.remove(delete=False)
        except BaseException:
            for source, target in reversed(moves):
                source.parent.mkdir(parents=True, exist_ok=True)
                os.rename(target, source)
            raise
        report["quarantine"] = str(destination)
        (destination / "removed-live.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    if args.report:
        Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps({key: value for key, value in report.items() if key != "items"}, ensure_ascii=False))


if __name__ == "__main__":
    main()

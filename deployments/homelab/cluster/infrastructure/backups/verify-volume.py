#!/usr/bin/env python3
"""Offline checks on volumes restored by the drill. The volumes stay read-only."""
import argparse
from contextlib import closing
import glob
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile


def files(pattern):
    found = [Path(path) for path in sorted(glob.glob(pattern, recursive=True)) if Path(path).is_file()]
    if not any(path.stat().st_size for path in found):
        raise SystemExit("missing or empty: " + pattern)
    return found


def check_sqlite(path):
    # A crash-consistent snapshot can hold an uncheckpointed WAL. Recover it in
    # a writable copy instead of trusting the main file alone.
    with tempfile.TemporaryDirectory() as work:
        copy = Path(work) / "database"
        shutil.copyfile(path, copy)
        if Path(str(path) + "-wal").is_file():
            shutil.copyfile(str(path) + "-wal", str(copy) + "-wal")
        with closing(sqlite3.connect(copy)) as database:
            if database.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                raise SystemExit("SQLite integrity check failed: " + str(path))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sqlite", action="append", default=[], help="database that must pass integrity_check")
    parser.add_argument("--json", action="append", default=[], help="glob whose files must all parse")
    parser.add_argument("--present", action="append", default=[], help="glob with at least one non-empty file")
    options = parser.parse_args()
    for path in options.sqlite:
        files(path)
        check_sqlite(Path(path))
    for pattern in options.json:
        for path in files(pattern):
            json.loads(path.read_bytes())
    for pattern in options.present:
        files(pattern)
    print("verified: " + ", ".join(options.sqlite + options.json + options.present), flush=True)


if __name__ == "__main__":
    main()

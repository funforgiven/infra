"""Velero pre-backup hook: write a verified online SQLite copy of Muse's database."""
import os
import sqlite3
from contextlib import closing
from pathlib import Path

source = Path("/data/db.sqlite")
recovery = Path("/data/recovery")
destination = recovery / "db.sqlite"
temporary = recovery / "db.sqlite.tmp"

def fsync_directory(directory: Path) -> None:
    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)

recovery.mkdir(mode=0o700, parents=True, exist_ok=True)
os.chmod(recovery, 0o700)
fsync_directory(recovery.parent)
temporary.unlink(missing_ok=True)

with closing(sqlite3.connect(
    f"file:{source}?mode=ro",
    uri=True,
)) as database, closing(sqlite3.connect(temporary)) as backup:
    database.backup(backup)
    result = backup.execute("PRAGMA quick_check").fetchone()
    if result != ("ok",):
        raise RuntimeError(f"backup integrity check failed: {result!r}")

os.chmod(temporary, 0o600)
with temporary.open("rb") as backup_file:
    os.fsync(backup_file.fileno())
os.replace(temporary, destination)
fsync_directory(recovery)

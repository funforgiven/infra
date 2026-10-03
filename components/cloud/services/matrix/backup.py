#!/usr/bin/env python3
"""Write integrity-checked PostgreSQL logical dumps for Kopia."""

import fcntl
import hashlib
import json
import os
import subprocess
import shutil
import time
from pathlib import Path


def main():
    directory = Path(os.environ.get("MATRIX_DUMPS_DIR", "/var/lib/matrix/dumps"))
    credentials = Path(os.environ.get("MATRIX_SECRET_DIR", "/run/matrix"))
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "dump.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        for incomplete in directory.glob("stage-*"):
            shutil.rmtree(incomplete)
        stage = directory / ("stage-" + str(time.time_ns()))
        stage.mkdir()
        manifest = {}
        for name in ("synapse", "mas"):
            target = stage / (name + ".dump")
            environment = dict(
                os.environ,
                PGPASSWORD=(credentials / (name + "-password")).read_text(),
            )
            subprocess.run(
                [
                    "pg_dump",
                    "-h",
                    os.environ.get("MATRIX_DB_HOST", "matrix-postgres"),
                    "-p",
                    os.environ.get("MATRIX_DB_PORT", "5432"),
                    "-U",
                    name,
                    "-d",
                    name,
                    "-Fc",
                    "-f",
                    str(target),
                ],
                env=environment,
                capture_output=True,
                check=True,
            )
            subprocess.run(
                ["pg_restore", "--list", str(target)], capture_output=True, check=True
            )
            with target.open("rb") as dump:
                manifest[target.name] = hashlib.file_digest(dump, "sha256").hexdigest()
        (stage / "manifest.json").write_text(json.dumps(manifest))
        completed = directory / stage.name.replace("stage-", "complete-")
        stage.replace(completed)
        for old in sorted(directory.glob("complete-*"), reverse=True)[3:]:
            shutil.rmtree(old)


if __name__ == "__main__":
    os.umask(0o077)
    try:
        main()
    except Exception:
        raise SystemExit(
            "Matrix logical backup failed; diagnostics suppressed."
        ) from None

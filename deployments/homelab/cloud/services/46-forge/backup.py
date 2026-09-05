#!/usr/bin/env python3
"""Quiesced, checked recovery archives; Velero copies only completed archives."""

import fcntl
import hashlib
import json
import os
from pathlib import Path
import secrets
import sqlite3
import sys
import tarfile
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

os.umask(0o077)
data = Path(os.environ.get("BACKUP_DATA", "/data"))
destination = Path(os.environ.get("BACKUP_DESTINATION", "/backups"))
control = Path(os.environ.get("BACKUP_CONTROL", "/control"))
database = os.environ["BACKUP_DATABASE"]
service = os.environ["BACKUP_SERVICE"]
last_error = 0


class Metrics(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/metrics":
            self.send_error(404)
            return
        completed = 0
        for marker in destination.glob(f"{service}-*.tar.gz.json"):
            try:
                completed = max(completed, json.loads(marker.read_text())["completed_at"])
            except (ValueError, KeyError, FileNotFoundError):
                continue
        body = (f'forge_backup_completed_timestamp_seconds{{service="{service}"}} {completed}\n'
                f'forge_backup_error_timestamp_seconds{{service="{service}"}} {last_error}\n').encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; version=0.0.4")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        pass


def backup_once():
    destination.mkdir(parents=True, exist_ok=True)
    with (control / "lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        # Wait for the supervisor to acknowledge the previous release before
        # issuing a new nonce (the scheduled job and Velero hook share this lock).
        acknowledgement_deadline = time.monotonic() + 60
        while (control / "paused").exists():
            if time.monotonic() > acknowledgement_deadline:
                raise TimeoutError("previous maintenance window did not close")
            time.sleep(0.2)
        nonce = secrets.token_hex(16)
        deadline = int(time.time()) + 900
        request = control / "request"
        temporary_request = control / ("request." + nonce)
        temporary_request.write_text(f"{deadline} {nonce}\n")
        temporary_request.replace(request)
        stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        archive = destination / f"{service}-{stamp}-{nonce[:8]}.tar.gz"
        partial = archive.with_suffix(archive.suffix + ".partial")
        manifest = archive.with_suffix(archive.suffix + ".json")

        def paused():
            try:
                return (control / "paused").read_text().strip() == nonce
            except FileNotFoundError:
                return False

        def check_window(info=None):
            if time.time() >= deadline - 10 or not paused():
                raise RuntimeError("backup maintenance window ended")
            return info

        try:
            while not paused():
                if time.time() >= deadline - 780:
                    raise TimeoutError("application did not stop for backup")
                time.sleep(0.2)
            db_path = data / database
            with sqlite3.connect(db_path.as_uri() + "?mode=ro", uri=True) as db:
                result = db.execute("PRAGMA integrity_check").fetchall()
                if result != [("ok",)]:
                    raise RuntimeError("source SQLite integrity check failed")
            check_window()
            with tarfile.open(partial, "w:gz", compresslevel=1) as output:
                output.add(data, arcname="data", filter=check_window)
            check_window()
            with partial.open("rb") as source:
                checksum = hashlib.file_digest(source, "sha256").hexdigest()
            check_window()
            partial.replace(archive)
            manifest_partial = manifest.with_suffix(".json.partial")
            manifest_partial.write_text(json.dumps({
                "service": service,
                "database": database,
                "archive": archive.name,
                "sha256": checksum,
                "completed_at": int(time.time()),
                "sqlite_integrity": "ok",
                "quiesced": True,
            }, indent=2) + "\n")
            manifest_partial.replace(manifest)
            print(f"Completed {service} recovery archive {archive.name}", flush=True)
            # Manifests are the completion markers. Never select a partial file.
            for old in sorted(destination.glob(f"{service}-*.tar.gz.json"), reverse=True)[7:]:
                old.with_suffix("").unlink(missing_ok=True)
                old.unlink()
        finally:
            partial.unlink(missing_ok=True)
            if request.exists() and request.read_text().split()[-1] == nonce:
                request.unlink()


if __name__ == "__main__":
    if sys.argv[1:] == ["--once"]:
        backup_once()
    else:
        threading.Thread(target=HTTPServer(("0.0.0.0", 9900), Metrics).serve_forever, daemon=True).start()
        while not (data / database).is_file():
            time.sleep(10)
        time.sleep(60)
        while True:
            try:
                backup_once()
                time.sleep(21600)
            except Exception as error:
                last_error = int(time.time())
                print(f"Backup failed: {type(error).__name__}: {error}", flush=True)
                time.sleep(300)

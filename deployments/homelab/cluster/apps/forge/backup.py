#!/usr/bin/env python3
"""Recovery metrics and a non-disruptive Velero freshness gate."""

from contextlib import closing
import os
from pathlib import Path
import sqlite3
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from recovery_archive import completed_archives, prepare_offsite

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
        archives = completed_archives(destination)
        completed = archives[-1][0] if archives else 0
        body = (f'forge_backup_completed_timestamp_seconds{{service="{service}"}} {completed}\n'
                f'forge_backup_error_timestamp_seconds{{service="{service}"}} {last_error}\n')
        if service == "forgejo":
            # Forgejo 15 does not export Actions queue metrics. Read only
            # aggregate job state; never expose workflow contents or identities.
            try:
                # sqlite3's transaction context does not close the connection.
                # Release its page cache and file descriptors on every scrape.
                with closing(sqlite3.connect((data / database).as_uri() + "?mode=ro", uri=True, timeout=2)) as db:
                    counts = dict(db.execute("SELECT status, COUNT(*) FROM action_run_job GROUP BY status"))
                    oldest = db.execute("SELECT COALESCE(MIN(updated), 0) FROM action_run_job WHERE status = 5").fetchone()[0]
                for status, name in [(1, "success"), (2, "failure"), (5, "waiting"), (6, "running"), (7, "blocked")]:
                    body += f'forge_actions_jobs{{status="{name}"}} {counts.get(status, 0)}\n'
                body += f'forge_actions_oldest_waiting_timestamp_seconds {oldest}\nforge_actions_metrics_up 1\n'
            except (OSError, sqlite3.Error):
                body += 'forge_actions_metrics_up 0\n'
        body = body.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; version=0.0.4")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        pass



if __name__ == "__main__":
    if sys.argv[1:] == ["--once"]:
        # Snapshot exports run independently. Offsite backup must never stop
        # Forgejo or silently accept a stale recovery source.
        manifest = prepare_offsite(destination)
        print(f"Using verified recovery archive {manifest['archive']}", flush=True)
    else:
        HTTPServer(("0.0.0.0", 9900), Metrics).serve_forever()

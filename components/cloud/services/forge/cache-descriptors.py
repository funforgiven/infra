#!/usr/bin/env python3
"""Resolve cache scopes from Forgejo 15.0.7's existing SQLite database, read-only.

The authenticated queue supplies job ID and current attempt. Only fixed metadata
is returned to trusted platform brokers; workflow bodies and credentials are never
selected. Keep the existing database/WAL/SHM volume mounted read-only.
"""
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import socket
import sqlite3
import threading
import time

DATABASE = Path('/data/data/forgejo.db')
SECRET_ROOT = Path('/run/cache-descriptors')
POLICIES = {
    'linux': ({'linux-quality', 'windows-build'}, 'linux-x86_64'),
    'macos': ({'macos-native'}, 'macos-x86_64'),
    'windows': ({'windows-native'}, 'windows-x86_64'),
}
# Pinned models/actions/{run,run_job,status}.go: Waiting=5, Running=6.
# PrepareNextAttempt increments before INSERT/requeue; task creation copies the
# current job attempt. Never add one to the authenticated queue's attempt.
QUERY = '''SELECT j.id, j.attempt, j.run_id, a.commit_sha, a.trigger_event,
                  a.ref, j.name, j.runs_on, j.job_id
           FROM action_run_job AS j
           JOIN action_run AS a ON a.id=j.run_id AND a.repo_id=j.repo_id
               AND a.owner_id=j.owner_id AND a.commit_sha=j.commit_sha
           JOIN repository AS r ON r.id=j.repo_id AND r.owner_id=j.owner_id
           WHERE j.id=? AND j.attempt=? AND j.status IN (5,6)
             AND a.status IN (5,6) AND a.need_approval=0
             AND r.owner_name='funforgiven' AND r.lower_name='atollion' '''
READ_COLUMNS = {
    'action_run_job': {'id', 'attempt', 'run_id', 'repo_id', 'owner_id', 'commit_sha',
                       'name', 'runs_on', 'job_id', 'status'},
    'action_run': {'id', 'repo_id', 'owner_id', 'commit_sha', 'trigger_event', 'ref', 'status', 'need_approval'},
    'repository': {'id', 'owner_id', 'owner_name', 'lower_name'},
}


class Refused(Exception):
    def __init__(self, status):
        self.status = status


def require(ok, status=404):
    if not ok:
        raise Refused(status)


def authorize_sql(operation, table, column, _database, _trigger):
    if operation == sqlite3.SQLITE_SELECT:
        return sqlite3.SQLITE_OK
    if operation == sqlite3.SQLITE_READ and column in READ_COLUMNS.get(table, set()):
        return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY


class Descriptors:
    def __init__(self, database=DATABASE, secret_root=SECRET_ROOT):
        self.database = Path(database)
        require(self.database.is_file() and not self.database.is_symlink(), 503)
        self.keys = {}
        for platform in POLICIES:
            key = (Path(secret_root) / f'cache-{platform}-broker').read_bytes().strip()
            require(32 <= len(key) <= 256 and b'\n' not in key and b'\r' not in key, 503)
            self.keys[platform] = key
        require(len(set(self.keys.values())) == len(self.keys), 503)

    def authenticate(self, authorization):
        matches = [platform for platform, key in self.keys.items()
                   if hmac.compare_digest(authorization, b'Bearer ' + key)]
        require(len(matches) == 1, 403)
        return matches[0]

    def connect(self):
        # mode=ro honors the live WAL; immutable=1 would incorrectly ignore it.
        connection = sqlite3.connect(self.database.absolute().as_uri() + '?mode=ro', uri=True, timeout=2)
        connection.execute('PRAGMA query_only=ON')
        connection.execute('PRAGMA trusted_schema=OFF')
        deadline = time.monotonic() + 2
        connection.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
        connection.set_authorizer(authorize_sql)
        return connection

    def get(self, job_id, attempt, platform):
        require(type(job_id) is int and type(attempt) is int and
                0 < job_id < 2**63 and 0 < attempt < 2**63 and platform in POLICIES, 400)
        connection = self.connect()
        try:
            row = connection.execute(QUERY, (job_id, attempt)).fetchone()
        finally:
            connection.close()
        require(row is not None)
        identity, current, run_id, head, event, ref, name, labels_raw, workflow_job = row
        require(type(run_id) is int and run_id > 0 and isinstance(head, str)
                and re.fullmatch(r'[0-9a-f]{40}', head))
        require(isinstance(labels_raw, str) and len(labels_raw) <= 2048)
        labels = json.loads(labels_raw)
        names, label = POLICIES[platform]
        require(name in names and workflow_job == name and labels == [label], 403)
        require((event == 'pull_request' and isinstance(ref, str)
                 and re.fullmatch(r'refs/pull/[1-9][0-9]*/(?:head|merge)', ref)) or
                (event in {'push', 'workflow_dispatch'} and isinstance(ref, str)
                 and re.fullmatch(r'refs/heads/[A-Za-z0-9_./-]{1,240}', ref)))
        return {'repository': 'funforgiven/atollion', 'job_id': identity, 'attempt': current,
                'run_id': run_id, 'head': head, 'event_name': event, 'ref': ref,
                'name': name, 'runs_on': labels}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def answer(self, status, value=None):
        raw = b'' if value is None else json.dumps(value, separators=(',', ':')).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(raw)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Connection', 'close')
        self.end_headers()
        self.wfile.write(raw)
        self.close_connection = True

    def do_GET(self):
        try:
            if self.path == '/healthz':
                return self.answer(200, {'status': 'ready'})
            require(len(self.headers.get_all('Authorization', [])) == 1, 403)
            platform = self.server.descriptors.authenticate(self.headers['Authorization'].encode())
            match = re.fullmatch(r'/v1/jobs/([1-9][0-9]{0,18})\?attempt=([1-9][0-9]{0,18})', self.path)
            require(match is not None, 404)
            self.answer(200, self.server.descriptors.get(int(match[1]), int(match[2]), platform))
        except Refused as error:
            self.answer(error.status)
        except (OSError, ValueError, TypeError, sqlite3.Error):
            self.answer(503)  # Never return SQL diagnostics, paths, headers or data.

    def do_POST(self):
        self.answer(405)
    do_PUT = do_PATCH = do_DELETE = do_POST


class Server(ThreadingHTTPServer):
    daemon_threads = True
    def __init__(self, address, descriptors):
        super().__init__(address, Handler)
        self.descriptors = descriptors
        self.slots = threading.BoundedSemaphore(16)

    def process_request(self, request, address):
        if not self.slots.acquire(blocking=False):
            request.close()
            return
        try:
            super().process_request(request, address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request, address):
        request.settimeout(5)
        def close():
            try:
                request.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        deadline = threading.Timer(10, close)
        deadline.daemon = True
        deadline.start()
        try:
            super().process_request_thread(request, address)
        finally:
            deadline.cancel()
            self.slots.release()

    def handle_error(self, *_):
        pass


if __name__ == '__main__':
    Server(('0.0.0.0', 8083), Descriptors()).serve_forever()

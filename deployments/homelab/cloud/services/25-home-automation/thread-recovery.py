#!/usr/bin/env python3
"""Verify Thread recovery without running OTBR; export health without secrets."""
import argparse
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
from pathlib import Path
import re
import signal
import sys
import tarfile
import urllib.request


def verify_dataset(payload):
    text = payload.decode('ascii').strip()
    if not re.fullmatch(r'(?:[0-9a-fA-F]{2}){10,255}', text):
        raise ValueError('Invalid Thread dataset encoding')
    data, fields, offset = bytes.fromhex(text), {}, 0
    while offset < len(data):
        if offset + 2 > len(data):
            raise ValueError('Truncated Thread dataset header')
        kind, size = data[offset:offset + 2]
        offset += 2
        if kind in fields or offset + size > len(data):
            raise ValueError('Duplicate or truncated Thread dataset field')
        fields[kind] = data[offset:offset + size]
        offset += size
    for kind, size in {0: 3, 1: 2, 2: 8, 4: 16, 5: 16, 7: 8, 14: 8}.items():
        if len(fields.get(kind, b'')) != size:
            raise ValueError('Required Thread dataset field is missing or invalid')
    if not 1 <= len(fields.get(3, b'')) <= 16 or len(fields.get(12, b'')) not in (3, 4):
        raise ValueError('Invalid Thread name or security policy')
    if fields[0][0] != 0 or not 11 <= int.from_bytes(fields[0][1:], 'big') <= 26:
        raise ValueError('Unsupported Thread channel')


def verify(path):
    with tarfile.open(path, 'r:gz') as archive:
        members = archive.getmembers()
        expected = {'thread.tar.gz', 'dataset.txt', 'created-at', 'SHA256SUMS'}
        if len(members) != len(expected) or {m.name for m in members} != expected:
            raise ValueError('Unexpected Thread recovery members')
        if any(not m.isfile() or m.size > 16 * 1024 * 1024 for m in members):
            raise ValueError('Unsafe Thread recovery member')
        files = {m.name: archive.extractfile(m).read() for m in members}
    sums = {}
    for line in files['SHA256SUMS'].decode('ascii').splitlines():
        match = re.fullmatch(r'([0-9a-f]{64})  (thread.tar.gz|dataset.txt|created-at)', line)
        if not match or match[2] in sums:
            raise ValueError('Invalid Thread checksum manifest')
        sums[match[2]] = match[1]
    if set(sums) != expected - {'SHA256SUMS'}:
        raise ValueError('Incomplete Thread checksum manifest')
    for name, digest in sums.items():
        if hashlib.sha256(files[name]).hexdigest() != digest:
            raise ValueError('Thread recovery checksum mismatch')
    verify_dataset(files['dataset.txt'])
    with tarfile.open(fileobj=io.BytesIO(files['thread.tar.gz']), mode='r:gz') as archive:
        members = archive.getmembers()
        names = [m.name for m in members]
        if len(names) != len(set(names)):
            raise ValueError('Duplicate Thread state members')
        for member in members:
            parts = Path(member.name).parts
            if not parts or parts[0] != 'thread' or '..' in parts or not (member.isfile() or member.isdir()):
                raise ValueError('Unsafe Thread state path or type')
        if not any(m.isfile() and m.name.endswith('.data') and m.size > 0 for m in members):
            raise ValueError('Native Thread settings are missing')
    completed = int(files['created-at'])
    if completed <= 0:
        raise ValueError('Invalid Thread recovery timestamp')
    return completed


def serve():
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == '/healthz':
                body = b'ok\n'
            elif self.path == '/metrics':
                try:
                    completed = verify(Path('/backups/thread-recovery.tar.gz'))
                except (OSError, ValueError, tarfile.TarError, UnicodeError):
                    completed = 0
                try:
                    with urllib.request.urlopen('http://127.0.0.1:8081/node/state', timeout=3) as response:
                        attached = int(json.load(response) in ('leader', 'router', 'child'))
                except (OSError, ValueError):
                    attached = 0
                body = (f'home_automation_thread_backup_last_success_timestamp_seconds {completed}\n'
                        f'home_automation_thread_attached {attached}\n').encode()
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain; version=0.0.4')
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    ThreadingHTTPServer(('', 9000), Handler).serve_forever()


if __name__ == '__main__':
    signal.signal(signal.SIGTERM, lambda *_args: sys.exit(0))
    parser = argparse.ArgumentParser()
    parser.add_argument('--verify', type=Path)
    options = parser.parse_args()
    if options.verify:
        verify(options.verify)
        print('Thread archive and dataset verified without starting a border router.')
    else:
        serve()

#!/usr/bin/env python3
"""Produce a bounded, quiesced recovery archive; serve backup/application metrics."""
import argparse
from contextlib import closing
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import sqlite3
import tarfile
import tempfile
import threading
import time
import urllib.request
import uuid
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SERVICES = ('home-assistant', 'matter', 'mosquitto', 'zigbee2mqtt')
MAX_PAUSE = 180


def verify(path):
    """Check all members without extracting paths or starting any integration."""
    with tarfile.open(path, 'r:gz') as archive:
        members = archive.getmembers()
        names = [member.name for member in members]
        if len(names) != len(set(names)) or 'manifest.json' not in names:
            raise ValueError('Missing manifest or duplicate archive members')
        manifest = json.load(archive.extractfile('manifest.json'))
        if manifest['version'] != 1 or set(manifest['services']) != set(SERVICES):
            raise ValueError('Unexpected recovery schema')
        if set(names) != set(manifest['files']) | {'manifest.json'}:
            raise ValueError('Archive members do not match manifest')
        for member in members:
            if not member.isfile() or member.name.startswith('/') or '..' in Path(member.name).parts:
                raise ValueError('Unsafe archive member')
            if member.name == 'manifest.json':
                continue
            if Path(member.name).parts[0] not in SERVICES:
                raise ValueError('Unexpected state directory')
            digest = hashlib.sha256()
            with archive.extractfile(member) as stream:
                while chunk := stream.read(1024 * 1024):
                    digest.update(chunk)
            if digest.hexdigest() != manifest['files'][member.name]:
                raise ValueError('State checksum mismatch')
            if member.name.endswith('.json') or '/.storage/' in member.name:
                json.load(archive.extractfile(member))
            if member.name == 'home-assistant/home-assistant_v2.db':
                with tempfile.TemporaryDirectory() as directory:
                    database = Path(directory) / 'database.db'
                    with database.open('wb') as output:
                        shutil.copyfileobj(archive.extractfile(member), output)
                    with closing(sqlite3.connect(f'file:{database}?mode=ro', uri=True)) as connection:
                        if connection.execute('PRAGMA integrity_check').fetchone() != ('ok',):
                            raise ValueError('Home Assistant SQLite integrity check failed')
        for required in ('home-assistant/configuration.yaml', 'home-assistant/.storage/http',
                         'zigbee2mqtt/configuration.yaml'):
            if required not in manifest['files']:
                raise ValueError('Required configuration is missing')
        return manifest


def backup(state=Path('/state'), destination=Path('/backups'), control=Path('/control')):
    destination.mkdir(exist_ok=True)
    with (control / 'backup.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        deadline = int(time.time()) + MAX_PAUSE
        token = f'{deadline}:{uuid.uuid4().hex}'
        partial = destination / 'home-automation.partial.tar.gz'
        for name in SERVICES:
            (control / f'{name}.failed').unlink(missing_ok=True)
        try:
            (control / 'pause.new').write_text(token)
            os.replace(control / 'pause.new', control / 'pause')
            while True:
                if time.time() > deadline - 60:
                    raise TimeoutError('Applications did not quiesce within 120 seconds')
                if any((control / f'{name}.failed').exists() for name in SERVICES):
                    raise RuntimeError('An application did not shut down cleanly')
                if all((control / f'{name}.paused').exists()
                       and (control / f'{name}.paused').read_text() == token
                       for name in SERVICES):
                    if any((control / f'{name}.failed').exists() for name in SERVICES):
                        raise RuntimeError('An application did not shut down cleanly')
                    break
                time.sleep(0.5)
            # Clean HA shutdown normally checkpoints WAL. Ensure the archive's
            # SQLite main file is self-contained, and refuse a locked writer.
            database = state / 'home-assistant/home-assistant_v2.db'
            if database.exists():
                with closing(sqlite3.connect(database, timeout=1)) as connection:
                    result = connection.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()
                    if result and result[0] != 0:
                        raise RuntimeError('SQLite writer remains active')
            manifest = {'version': 1, 'created_at': int(time.time()),
                        'services': list(SERVICES), 'files': {}}
            with tarfile.open(partial, 'w:gz', compresslevel=1) as archive:
                for service in SERVICES:
                    for path in sorted((state / service).rglob('*')):
                        if time.time() > deadline - 5:
                            raise TimeoutError('Local archive exceeded the pause budget')
                        if path.is_symlink():
                            raise ValueError('State symlinks must be resolved before backup')
                        if not path.is_file():
                            continue
                        relative = path.relative_to(state).as_posix()
                        # Runtime caches and log history are not recovery state.
                        if '__pycache__' in path.parts or path.name.startswith('home-assistant.log'):
                            continue
                        with path.open('rb') as source:
                            manifest['files'][relative] = hashlib.file_digest(source, 'sha256').hexdigest()
                        archive.add(path, arcname=relative, recursive=False)
                payload = json.dumps(manifest, sort_keys=True).encode()
                member = tarfile.TarInfo('manifest.json')
                member.size, member.mode = len(payload), 0o600
                archive.addfile(member, io.BytesIO(payload))
            if time.time() >= deadline - 2:
                raise TimeoutError('Pause lease expired before archive completion')
        finally:
            (control / 'pause').unlink(missing_ok=True)
        # Writers resume before integrity checking and before offsite upload.
        try:
            verify(partial)
            os.replace(partial, destination / 'home-automation.tar.gz')
            temporary = destination / 'last-success.partial.json'
            temporary.write_text(json.dumps({'completed_at': int(time.time())}))
            os.replace(temporary, destination / 'last-success.json')
            print('Coordinated automation backup and integrity verification completed.', flush=True)
        finally:
            partial.unlink(missing_ok=True)


def mqtt_auth():
    def string(value):
        value = value.encode()
        return len(value).to_bytes(2, 'big') + value
    password = Path('/credentials/monitoring-password').read_text().strip()
    body = string('MQTT') + bytes([4, 0xC2, 0, 15])
    body += string('infra-health') + string('monitoring') + string(password)
    length, remaining = bytearray(), len(body)
    while True:
        value, remaining = remaining % 128, remaining // 128
        length.append(value | (128 if remaining else 0))
        if not remaining:
            break
    with socket.create_connection(('127.0.0.1', 1883), timeout=3) as connection:
        connection.sendall(b'\x10' + length + body)
        response = b''
        while len(response) < 4:
            chunk = connection.recv(4 - len(response))
            if not chunk:
                break
            response += chunk
        connection.sendall(b'\xe0\x00')
        return response == b'\x20\x02\x00\x00'


def serve():
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == '/healthz':
                body = b'ok\n'
            elif self.path == '/metrics':
                try:
                    completed = json.loads(Path('/backups/last-success.json').read_text())['completed_at']
                except (OSError, ValueError, KeyError):
                    completed = 0
                try:
                    mqtt = int(mqtt_auth())
                except (OSError, ValueError):
                    mqtt = 0
                try:
                    with urllib.request.urlopen('http://127.0.0.1:5580', timeout=3) as response:
                        matter = int(response.status == 200)
                except OSError:
                    matter = 0
                lines = [f'home_automation_backup_last_success_timestamp_seconds {completed}',
                         f'home_automation_mqtt_authenticated {mqtt}',
                         f'home_automation_matter_available {matter}',
                         f'home_automation_zigbee_enabled {int(os.environ.get("ZIGBEE_ENABLED") == "true")}']
                for service in SERVICES:
                    running = int(Path(f'/control/{service}.running').exists())
                    lines.append(f'home_automation_process_running{{service="{service}"}} {running}')
                body = ('\n'.join(lines) + '\n').encode()
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain; version=0.0.4')
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    threading.Thread(target=ThreadingHTTPServer(('', 9000), Handler).serve_forever,
                     daemon=True).start()
    time.sleep(180)
    while True:
        try:
            backup()
        except Exception as error:
            print(f'Automation backup failed: {type(error).__name__}', flush=True)
            time.sleep(300)
        else:
            time.sleep(21600)


if __name__ == '__main__':
    # Python running as container PID 1 must explicitly handle termination.
    # SystemExit also runs the backup's finally block and resumes writers.
    signal.signal(signal.SIGTERM, lambda *_args: sys.exit(0))
    os.umask(0o077)
    parser = argparse.ArgumentParser()
    parser.add_argument('--once', action='store_true')
    parser.add_argument('--verify', type=Path)
    options = parser.parse_args()
    if options.verify:
        verify(options.verify)
        print('Recovery archive verified without starting any application.')
    elif options.once:
        backup()
    else:
        serve()

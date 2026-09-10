"""Portable recovery archives from isolated, single-volume storage snapshots."""
from contextlib import closing
import fcntl
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import sqlite3
import tarfile
import time


DATABASE = 'data/forgejo.db'


def completed_archives(destination):
    result = []
    for pattern in ('forgejo-*.tar.json', 'forgejo-*.tar.gz.json'):
        for marker in destination.glob(pattern):
            try:
                manifest = json.loads(marker.read_text())
                archive = destination / manifest['archive']
                if archive.parent != destination or archive.is_symlink() or not archive.is_file():
                    continue
                if marker.name != archive.name + '.json' or manifest['database'] != DATABASE:
                    continue
                if not (manifest.get('quiesced') is True or
                        (manifest.get('consistency') == 'volume-snapshot' and manifest.get('snapshot_uid'))):
                    continue
                result.append((int(manifest['completed_at']), marker, manifest))
            except (OSError, ValueError, KeyError, TypeError):
                continue
    return sorted(result, key=lambda item: (item[0], item[1].name))


def require_recent_archive(destination, max_age=28800):
    archives = completed_archives(destination)
    if not archives or not 0 <= time.time() - archives[-1][2].get('captured_at', archives[-1][0]) < max_age:
        raise RuntimeError('No verified recovery archive less than eight hours old')
    return archives[-1][2]


def prepare_offsite(destination):
    # Serialize with publication/pruning. The lease covers a prune Job already
    # starting when Velero begins; the controller also checks live Backup state.
    with (destination / '.archive.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        manifest = require_recent_archive(destination)
        (destination / '.offsite-read-until').write_text(str(int(time.time()) + 3600))
        return manifest


def export_snapshot(source, destination, snapshot_uid, captured_at):
    # Only the separate exporter mounts /snapshot. Never accept the live mount.
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if source == Path('/data') or source == destination or source in destination.parents or destination in source.parents:
        raise ValueError('Snapshot and destination must be separate from live application storage')
    if not snapshot_uid or not 0 <= time.time() - captured_at < 3600:
        raise ValueError('A recent, identified storage snapshot is required')
    destination.mkdir(parents=True, exist_ok=True)
    with (destination / '.archive.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        # Velero's pinned Kopia version honors this default ignore file.
        ignore = destination / '.kopiaignore'
        ignore.write_text('*.partial\n.archive.lock\n.offsite-read-until\n')
        # Checkpoint WAL on the disposable clone, never on the live application.
        with closing(sqlite3.connect((source / DATABASE).as_uri() + '?mode=rw', uri=True)) as db:
            checkpoint = db.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()
            if checkpoint[0] != 0 or db.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
                raise RuntimeError('Snapshot SQLite recovery or integrity check failed')
        needed = sum(p.stat().st_size for p in source.rglob('*') if p.is_file() and not p.is_symlink())
        if shutil.disk_usage(destination).free < needed + 5 * 1024**3:
            raise RuntimeError('Insufficient backup space; existing archives were preserved')
        stamp = time.strftime('%Y%m%dT%H%M%SZ', time.gmtime(captured_at))
        archive = destination / f'forgejo-{stamp}-{secrets.token_hex(4)}.tar'
        partial = archive.with_suffix('.tar.partial')
        marker = archive.with_suffix('.tar.json')
        marker_partial = marker.with_suffix('.json.partial')
        try:
            # Uncompressed tar preserves stable content for Kopia's chunk
            # deduplication. Compressing the whole evolving tree defeats it.
            with tarfile.open(partial, 'w') as output:
                output.add(source, arcname='data')
            with partial.open('rb') as stream:
                os.fsync(stream.fileno())
                checksum = hashlib.file_digest(stream, 'sha256').hexdigest()
            manifest = {'service': 'forgejo', 'database': DATABASE, 'archive': archive.name,
                        'sha256': checksum, 'completed_at': int(time.time()),
                        'captured_at': captured_at, 'sqlite_integrity': 'ok',
                        'quiesced': False, 'consistency': 'volume-snapshot', 'snapshot_uid': snapshot_uid}
            partial.replace(archive)
            marker_partial.write_text(json.dumps(manifest, indent=2) + '\n')
            with marker_partial.open('rb') as stream:
                os.fsync(stream.fileno())
            marker_partial.replace(marker)
            directory_fd = os.open(destination, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
            print(f'Completed online recovery archive {archive.name} ({archive.stat().st_size} bytes)', flush=True)
            return manifest
        finally:
            partial.unlink(missing_ok=True)
            marker_partial.unlink(missing_ok=True)


def prune_archives(destination, keep=2):
    """Called by the controller only outside an active Velero backup."""
    if keep < 2:
        raise ValueError('Keep at least two verified recovery archives')
    with (destination / '.archive.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        lease = destination / '.offsite-read-until'
        if lease.exists() and int(lease.read_text()) > time.time():
            print('Retention deferred while offsite readers may be active.', flush=True)
            return
        archives = completed_archives(destination)
        # Do not retire the known-good format until online export has succeeded.
        if not archives or archives[-1][2].get('consistency') != 'volume-snapshot':
            return
        for _, marker, manifest in archives[:-keep]:
            marker.unlink()
            (destination / manifest['archive']).unlink()

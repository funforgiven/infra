#!/usr/bin/env python3
"""Retire the old in-process backup timer without restarting its container.

Use only for the initial migration to online snapshots. The old timer takes
/control/lock before requesting application shutdown; holding it prevents that
path while its metrics thread keeps serving. A compatibility marker lets that
thread observe real completed snapshot exports. The next planned pod/container
replacement starts the new metrics-only backup.py and needs no bridge.
"""
import fcntl
import json
import os
from pathlib import Path
import time

from recovery_archive import completed_archives


def publish_status(destination):
    archives = completed_archives(destination)
    if archives:
        # Intentionally not a restore manifest: its name differs from the real
        # archive's completion marker. New readers/retention ignore it, while
        # the old metrics thread only reads the real completed_at timestamp.
        marker = destination / 'forgejo-online-status.tar.gz.json'
        temporary = marker.with_suffix('.json.partial')
        temporary.write_text(json.dumps(archives[-1][2]) + '\n')
        temporary.replace(marker)


def run(control, destination):
    with (control / 'lock').open('a') as lock:
        # An existing backup or bridge must be inspected, never interrupted.
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if (control / 'request').exists() or (control / 'paused').exists():
            raise RuntimeError('An application maintenance request is active')
        (control / 'online-backup-bridge-ready').write_text(str(os.getpid()))
        while True:
            try:
                publish_status(destination)
            except (OSError, ValueError, KeyError) as error:
                # Metrics failure must not release the old shutdown timer.
                print(f'Legacy backup metrics bridge: {type(error).__name__}', flush=True)
            time.sleep(10)


if __name__ == '__main__':
    run(Path('/control'), Path('/backups'))

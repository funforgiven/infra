#!/usr/bin/env python3
"""Forced SSH command: boot one disposable Quickemu guest with one-job media.

Installed as an immutable Nix executable. Only the dedicated broker key may
invoke it via sudo. No user-supplied commands, paths or QEMU options are accepted.
"""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time

GOLDEN = Path('/var/lib/forge-golden/macos')
ACTIVE = Path('/var/lib/quickemu/macos')
UNIT = 'quickemu-macos.service'


def run(*args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def main():
    if os.geteuid() != 0 or len(sys.argv) != 1:
        raise RuntimeError('Only the authorized no-argument broker command may run')
    os.umask(0o077)
    raw = sys.stdin.buffer.read(16385)
    if len(raw) > 16384:
        raise ValueError('Enrollment exceeds its size limit')
    enrollment = json.loads(raw)
    if set(enrollment) != {'uuid', 'token', 'handle'}:
        raise ValueError('Unexpected enrollment fields')
    for value in enrollment.values():
        if not isinstance(value, str) or not 1 <= len(value) <= 4096 or any(ord(c) <= 32 for c in value):
            raise ValueError('Invalid ephemeral enrollment')
    lock = open('/run/forge-macos-job.lock', 'w')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    # The installer and a preceding job must be completely stopped. The broker
    # never interrupts a maintenance VM or reuses its writable disk.
    state = subprocess.run(['systemctl', 'is-active', UNIT], capture_output=True, text=True).stdout.strip()
    if state not in {'inactive', 'failed'}:
        raise RuntimeError('A macOS guest is already active')
    if ACTIVE.exists():
        raise RuntimeError('Previous guest state exists; inspect it before launching another job')
    manifest = json.loads((GOLDEN / 'manifest.json').read_text())
    required = {'disk.qcow2', 'OpenCore.qcow2', 'OVMF_CODE.fd', 'OVMF_VARS-1920x1080.fd'}
    if set(manifest['sha256']) != required:
        raise RuntimeError('Golden manifest does not contain the required image and firmware')
    for name, digest in manifest['sha256'].items():
        path = GOLDEN / name
        if path.is_symlink() or path.stat().st_uid != 0 or path.stat().st_mode & 0o022:
            raise RuntimeError('Golden files must be root-owned and immutable to runner users')
        with path.open('rb') as source:
            if hashlib.file_digest(source, 'sha256').hexdigest() != digest:
                raise RuntimeError('Golden image checksum mismatch')
    ACTIVE.mkdir(mode=0o700)
    try:
        for name in required - {'disk.qcow2'}:
            shutil.copy2(GOLDEN / name, ACTIVE / name)
            # Golden firmware is read-only; each guest owns mutable copies.
            (ACTIVE / name).chmod(0o600)
        run('qemu-img', 'create', '-q', '-f', 'qcow2', '-F', 'qcow2', '-b', str(GOLDEN / 'disk.qcow2'), str(ACTIVE / 'disk.qcow2'))
        (ACTIVE / 'firmware.sha256').write_text(''.join(manifest['sha256'][name] + '  ' + name + '\n' for name in ['OpenCore.qcow2', 'OVMF_CODE.fd']))
        with tempfile.TemporaryDirectory(prefix='forge-enrollment-', dir='/run') as staging:
            Path(staging, 'enrollment.json').write_text(json.dumps(enrollment))
            run('mkisofs', '-quiet', '-J', '-r', '-V', 'FORGEJOB', '-o', str(ACTIVE / 'job.iso'), staging,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for root, directories, files in os.walk(ACTIVE):
            shutil.chown(root, user='quickemu', group='quickemu')
            for name in files:
                shutil.chown(Path(root, name), user='quickemu', group='quickemu')
        # An inactive unit may have been garbage-collected by systemd. In that
        # case reset-failed reports "not loaded"; starting the unit is valid.
        subprocess.run(['systemctl', 'reset-failed', UNIT], check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        run('systemctl', 'start', UNIT, stdout=subprocess.DEVNULL)
        print('Started fresh macOS overlay with one-job enrollment media.', flush=True)
        end = time.monotonic() + 8100
        while time.monotonic() < end:
            state = subprocess.run(['systemctl', 'is-active', UNIT], capture_output=True, text=True).stdout.strip()
            if state == 'inactive':
                print('macOS guest shut down after its job.', flush=True)
                return
            if state == 'failed':
                raise RuntimeError('macOS guest failed')
            # SSH without a PTY need not deliver SIGHUP when its client exits.
            # A write detects the closed broker channel and enters the same
            # finally cleanup as a timeout, without any guest credential access.
            print('macOS guest running; broker channel checked.', flush=True)
            time.sleep(10)
        raise RuntimeError('macOS guest exceeded its external deadline')
    finally:
        # Never unlink an active QEMU disk. A failed stop leaves evidence and
        # prevents the next invocation from silently reusing the old workspace.
        run('systemctl', 'stop', UNIT, stdout=subprocess.DEVNULL)
        shutil.rmtree(ACTIVE)
        print('Removed macOS writable overlay, enrollment media and mutable firmware.', flush=True)


if __name__ == '__main__':
    def stop(_signum, _frame):
        raise InterruptedError('Broker connection terminated')
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGHUP, stop)
    try:
        main()
    except Exception as error:
        print('macOS launcher failed:', str(error) if isinstance(error, (RuntimeError, InterruptedError)) else type(error).__name__, file=sys.stderr)
        raise SystemExit(1) from None

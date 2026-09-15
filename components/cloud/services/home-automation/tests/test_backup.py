import importlib.util
from contextlib import closing
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[5]
SOURCE = ROOT / 'deployments/homelab/cloud/services/25-home-automation'
spec = importlib.util.spec_from_file_location('automation_backup', SOURCE / 'backup.py')
backup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backup)


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.state, self.control, self.destination = [self.root / name for name in ('state', 'control', 'backups')]
        self.control.mkdir()
        self.destination.mkdir()
        for service in backup.SERVICES:
            (self.state / service).mkdir(parents=True)
        ha = self.state / 'home-assistant'
        (ha / '.storage').mkdir()
        (ha / '.storage/http').write_text('{}')
        (ha / 'configuration.yaml').write_text('default_config:\n')
        (self.state / 'zigbee2mqtt/configuration.yaml').write_text('version: 5\n')
        (self.state / 'matter/fabric.json').write_text('{"fabric": "preserved"}')
        with closing(sqlite3.connect(ha / 'home-assistant_v2.db')) as connection, connection:
            connection.execute('CREATE TABLE states (state TEXT)')
            connection.execute("INSERT INTO states VALUES ('on')")

    def snapshot(self, failed=None):
        def acknowledge():
            deadline = time.monotonic() + 5
            while not (self.control / 'pause').exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            token = (self.control / 'pause').read_text()
            if failed:
                (self.control / f'{failed}.failed').touch()
            for service in backup.SERVICES:
                (self.control / f'{service}.paused').write_text(token)
        worker = threading.Thread(target=acknowledge)
        worker.start()
        try:
            backup.backup(self.state, self.destination, self.control)
        finally:
            worker.join(timeout=5)
        return self.destination / 'home-automation.tar.gz'

    def test_archive_preserves_fabric_and_sqlite_and_resumes_writers(self):
        archive = self.snapshot()
        manifest = backup.verify(archive)
        self.assertIn('matter/fabric.json', manifest['files'])
        self.assertIn('home-assistant/home-assistant_v2.db', manifest['files'])
        self.assertFalse((self.control / 'pause').exists())
        self.assertTrue((self.destination / 'last-success.json').exists())

    def test_failed_shutdown_never_replaces_the_previous_backup(self):
        archive = self.snapshot()
        previous = archive.read_bytes()
        with self.assertRaises(RuntimeError):
            self.snapshot(failed='matter')
        self.assertEqual(previous, archive.read_bytes())
        self.assertFalse((self.control / 'pause').exists())

    def test_symlink_failure_always_resumes_writers(self):
        (self.state / 'matter/external').symlink_to('/etc/passwd')
        with self.assertRaises(ValueError):
            self.snapshot()
        self.assertFalse((self.control / 'pause').exists())
        self.assertFalse((self.destination / 'last-success.json').exists())

    def test_changed_payload_and_duplicate_members_are_rejected(self):
        good = self.snapshot()
        for duplicate in (False, True):
            bad = self.destination / f'bad-{duplicate}.tar.gz'
            with tarfile.open(good) as source, tarfile.open(bad, 'w:gz') as output:
                for member in source.getmembers():
                    content = source.extractfile(member).read()
                    if member.name == 'matter/fabric.json':
                        content = b'{"fabric":"wrong"}' if not duplicate else content
                    member.size = len(content)
                    output.addfile(member, io.BytesIO(content))
                    if duplicate and member.name == 'matter/fabric.json':
                        output.addfile(member, io.BytesIO(content))
            with self.assertRaises(ValueError):
                backup.verify(bad)

    def test_corrupt_sqlite_is_rejected_even_when_hashes_match(self):
        (self.state / 'home-assistant/home-assistant_v2.db').write_bytes(b'not a sqlite database')
        with self.assertRaises(sqlite3.DatabaseError):
            self.snapshot()
        self.assertFalse((self.control / 'pause').exists())


class VolumeSelectionTests(unittest.TestCase):
    def test_velero_default_filesystem_mode_copies_only_the_verified_archive(self):
        # Velero's cluster-wide opt-out mode includes emptyDir volumes too.
        # Derive selection from the pod volumes so new runtime volumes must be
        # excluded explicitly rather than silently entering offsite backups.
        for filename in ('workload.yaml', 'thread.yaml'):
            documents = list(yaml.safe_load_all((SOURCE / filename).read_text()))
            workload = next(item for item in documents if item['kind'] == 'StatefulSet')
            template = workload['spec']['template']
            excluded = set(template['metadata']['annotations']['backup.velero.io/backup-volumes-excludes'].split(','))
            selected = {volume['name'] for volume in template['spec']['volumes']
                        if volume['name'] not in excluded
                        and not {'hostPath', 'configMap', 'secret', 'projected'}.intersection(volume)}
            self.assertEqual({'backups'}, selected, filename)


class SupervisorTests(unittest.TestCase):
    def test_graceful_pause_resume_and_expired_lease(self):
        with tempfile.TemporaryDirectory() as temporary:
            control = Path(temporary)
            child = control / 'child.py'
            child.write_text('import signal,time,sys\nsignal.signal(signal.SIGTERM,lambda *_:sys.exit(0))\nwhile True: time.sleep(0.1)\n')
            process = subprocess.Popen(['sh', str(SOURCE / 'run-service.sh'), 'test', sys.executable, str(child)], env={**os.environ, 'CONTROL_DIRECTORY': str(control)})
            try:
                def wait_for(predicate):
                    deadline = time.monotonic() + 8
                    while time.monotonic() < deadline:
                        if predicate(): return
                        time.sleep(0.05)
                    self.fail('Supervisor did not reach expected state')
                wait_for(lambda: (control / 'test.running').exists())
                (control / 'pause').write_text(str(int(time.time()) + 20))
                wait_for(lambda: (control / 'test.paused').exists())
                self.assertFalse((control / 'test.failed').exists())
                self.assertFalse((control / 'test.running').exists())
                # Simulate the backup controller disappearing without cleanup.
                (control / 'pause').write_text(str(int(time.time()) - 1))
                wait_for(lambda: (control / 'test.running').exists())
                self.assertIsNone(process.poll())
            finally:
                process.terminate()
                process.wait(timeout=5)


if __name__ == '__main__':
    unittest.main()

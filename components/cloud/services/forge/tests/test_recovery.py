import hashlib
import shutil
from unittest.mock import patch
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parents[5]
SCRIPTS = ROOT / "deployments/homelab/cloud/services/46-forge"
sys.path.insert(0, str(SCRIPTS))
import recovery_archive


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        for name in ("data", "backups", "control"):
            (self.root / name).mkdir()
        self.environment = {**os.environ, "BACKUP_SERVICE": "forgejo", "BACKUP_DATABASE": "data/forgejo.db",
                            **{"BACKUP_" + key.upper(): str(self.root / value) for key, value in
                               (("data", "data"), ("destination", "backups"), ("control", "control"))}}
        # Each transaction refers to an already-written repository object. The
        # restore must contain both the committed row and its exact file bytes.
        (self.root / "data/data").mkdir()
        self.app = self.root / "app.py"
        (self.root / "child.py").write_text('''import os, signal, time
from pathlib import Path
signal.signal(signal.SIGTERM, signal.SIG_IGN)
path = Path(os.environ["BACKUP_DATA"]) / "child"
while True:
    path.write_text(str(time.time_ns()))
    time.sleep(.02)
''')
        self.app.write_text('''import os, sqlite3, subprocess, sys, time
from pathlib import Path
root = Path(os.environ["BACKUP_DATA"])
subprocess.Popen([sys.executable, str(root.parent / "child.py")])
db = sqlite3.connect(root / "data/forgejo.db")
db.execute("PRAGMA journal_mode=WAL")
db.execute("CREATE TABLE IF NOT EXISTS objects (id INTEGER PRIMARY KEY, content TEXT)")
while True:
    value = time.time_ns()
    (root / str(value)).write_text(str(value))
    db.execute("INSERT INTO objects VALUES (?, ?)", (value, str(value)))
    db.commit()
    time.sleep(.05)
''')
        self.service = subprocess.Popen(["sh", str(SCRIPTS / "run-service.sh"), sys.executable, str(self.app)],
                                        env=self.environment, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.await_condition(lambda: (self.root / "data/data/forgejo.db").exists())

    def tearDown(self):
        self.service.terminate()
        self.service.wait(timeout=55)
        self.temp.cleanup()

    def await_condition(self, condition, timeout=15):
        until = time.monotonic() + timeout
        while not condition():
            if time.monotonic() > until:
                self.fail("timed out awaiting service state")
            time.sleep(.05)

    def capture_fixture(self):
        # Simulate an atomic storage snapshot. Production uses Cinder/CSI;
        # this fixture's supervisor makes the frozen clone deterministic.
        request = self.root / 'control/request'
        request.write_text(f"{int(time.time()) + 15} fixture-snapshot\n")
        self.await_condition(lambda: (self.root / 'control/paused').exists())
        snapshot = self.root / 'snapshot'
        shutil.copytree(self.root / 'data', snapshot)
        request.unlink()
        self.await_condition(lambda: not (self.root / 'control/paused').exists())
        return snapshot

    def test_concurrent_exports_restore_database_and_objects_while_service_runs(self):
        snapshot = self.capture_fixture()
        before = len(list((self.root / 'data').iterdir()))
        script = ("import sys; from pathlib import Path; sys.path.insert(0, sys.argv[1]); "
                  "from recovery_archive import export_snapshot; "
                  "export_snapshot(Path(sys.argv[2]), Path(sys.argv[3]), 'fixture-snapshot', int(sys.argv[4]))")
        backups = [subprocess.Popen([sys.executable, '-c', script, str(SCRIPTS), str(snapshot),
                                    str(self.root / 'backups'), str(int(time.time()))],
                                    stdout=subprocess.DEVNULL) for _ in range(2)]
        for process in backups:
            self.assertEqual(process.wait(timeout=30), 0)
        self.await_condition(lambda: len(list((self.root / 'data').iterdir())) > before)
        self.assertFalse((self.root / 'control/request').exists())
        markers = list((self.root / 'backups').glob('*.tar.json'))
        self.assertEqual(len(markers), 2)
        for number, marker in enumerate(markers):
            manifest = json.loads(marker.read_text())
            self.assertFalse(manifest['quiesced'])
            self.assertEqual(manifest['consistency'], 'volume-snapshot')
            archive = marker.parent / manifest['archive']
            self.assertEqual(hashlib.sha256(archive.read_bytes()).hexdigest(), manifest['sha256'])
            target = self.root / f'restored-{number}'
            with tarfile.open(archive) as recovery:
                recovery.extractall(target, filter='data')
            with sqlite3.connect(target / 'data/data/forgejo.db') as db:
                self.assertEqual(db.execute('PRAGMA integrity_check').fetchone(), ('ok',))
                rows = db.execute('SELECT id, content FROM objects').fetchall()
                self.assertTrue(rows)
                for identity, content in rows:
                    self.assertEqual((target / 'data' / str(identity)).read_text(), content)
        # The Velero hook now only checks freshness: no application pause.
        hook = subprocess.run([sys.executable, str(SCRIPTS / 'backup.py'), '--once'],
                              env=self.environment, capture_output=True, timeout=5)
        self.assertEqual(hook.returncode, 0, hook.stderr)
        self.assertFalse((self.root / 'control/request').exists())
        self.assertIsNone(self.service.poll())

    def test_failed_export_keeps_recovery_history_and_cleans_partial_files(self):
        snapshot = self.capture_fixture()
        destination = self.root / 'backups'
        first = recovery_archive.export_snapshot(snapshot, destination, 'fixture', int(time.time()))
        with patch.object(recovery_archive.tarfile, 'open', side_effect=OSError('disk error')):
            with self.assertRaises(OSError):
                recovery_archive.export_snapshot(snapshot, destination, 'fixture', int(time.time()))
        self.assertEqual(len(recovery_archive.completed_archives(destination)), 1)
        self.assertTrue((destination / first['archive']).is_file())
        self.assertFalse(list(destination.glob('*.partial')))
        with patch.object(recovery_archive.shutil, 'disk_usage', return_value=shutil._ntuple_diskusage(100, 99, 1)):
            with self.assertRaisesRegex(RuntimeError, 'space'):
                recovery_archive.export_snapshot(snapshot, destination, 'fixture', int(time.time()))
        self.assertTrue((destination / first['archive']).is_file())

    def test_retention_and_freshness_fail_closed(self):
        snapshot = self.capture_fixture()
        destination = self.root / 'backups'
        with self.assertRaises(RuntimeError):
            recovery_archive.require_recent_archive(destination)
        for i in range(3):
            recovery_archive.export_snapshot(snapshot, destination, 'fixture', int(time.time()) - (3 - i))
        recovery_archive.prepare_offsite(destination)
        recovery_archive.prune_archives(destination)
        self.assertEqual(len(recovery_archive.completed_archives(destination)), 3)
        (destination / '.offsite-read-until').write_text('0')
        recovery_archive.prune_archives(destination)
        self.assertEqual(len(recovery_archive.completed_archives(destination)), 2)
        self.assertEqual(len(list(destination.glob('*.tar'))), 2)
        with patch.object(recovery_archive.time, 'time', return_value=time.time() + 30000):
            with self.assertRaises(RuntimeError):
                recovery_archive.require_recent_archive(destination)
        with self.assertRaises(ValueError):
            recovery_archive.export_snapshot(Path('/data'), destination, 'fixture', int(time.time()))

    def test_abandoned_backup_cannot_leave_service_paused(self):
        (self.root / "control/request").write_text(f"{int(time.time()) + 3} abandoned\n")
        self.await_condition(lambda: (self.root / "control/paused").exists())
        self.await_condition(lambda: not (self.root / "control/paused").exists())
        before = len(list((self.root / "data").iterdir()))
        self.await_condition(lambda: len(list((self.root / "data").iterdir())) > before)
        self.assertIsNone(self.service.poll())

    def test_quiescence_stops_subprocesses_that_ignore_term(self):
        self.await_condition(lambda: (self.root / "data/child").exists())
        (self.root / "control/request").write_text(f"{int(time.time()) + 10} subprocess-check\n")
        self.await_condition(lambda: (self.root / "control/paused").exists())
        before = (self.root / "data/child").read_text()
        time.sleep(.2)
        self.assertEqual((self.root / "data/child").read_text(), before)
        (self.root / "control/request").unlink()
        self.await_condition(lambda: not (self.root / "control/paused").exists())


if __name__ == "__main__":
    unittest.main()

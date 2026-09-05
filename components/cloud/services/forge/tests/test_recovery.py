import hashlib
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


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        for name in ("data", "backups", "control"):
            (self.root / name).mkdir()
        self.environment = {**os.environ, "BACKUP_SERVICE": "fixture", "BACKUP_DATABASE": "state.db",
                            **{"BACKUP_" + key.upper(): str(self.root / value) for key, value in
                               (("data", "data"), ("destination", "backups"), ("control", "control"))}}
        # Each transaction refers to an already-written repository object. The
        # restore must contain both the committed row and its exact file bytes.
        self.app = self.root / "app.py"
        self.app.write_text('''import os, sqlite3, time
from pathlib import Path
root = Path(os.environ["BACKUP_DATA"])
db = sqlite3.connect(root / "state.db")
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
        self.await_condition(lambda: (self.root / "data/state.db").exists())

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

    def test_concurrent_backups_restore_database_and_objects(self):
        backups = [subprocess.Popen([sys.executable, str(SCRIPTS / "backup.py"), "--once"],
                                    env=self.environment, stdout=subprocess.DEVNULL) for _ in range(2)]
        for process in backups:
            self.assertEqual(process.wait(timeout=30), 0)
        markers = list((self.root / "backups").glob("*.json"))
        self.assertEqual(len(markers), 2)
        for number, marker in enumerate(markers):
            manifest = json.loads(marker.read_text())
            archive = marker.parent / manifest["archive"]
            self.assertEqual(hashlib.sha256(archive.read_bytes()).hexdigest(), manifest["sha256"])
            target = self.root / f"restored-{number}"
            with tarfile.open(archive) as recovery:
                recovery.extractall(target, filter="data")
            with sqlite3.connect(target / "data/state.db") as db:
                self.assertEqual(db.execute("PRAGMA integrity_check").fetchone(), ("ok",))
                rows = db.execute("SELECT id, content FROM objects").fetchall()
                self.assertTrue(rows)
                for identity, content in rows:
                    self.assertEqual((target / "data" / str(identity)).read_text(), content)
        self.await_condition(lambda: not (self.root / "control/paused").exists())
        self.assertIsNone(self.service.poll())

    def test_abandoned_backup_cannot_leave_service_paused(self):
        (self.root / "control/request").write_text(f"{int(time.time()) + 3} abandoned\n")
        self.await_condition(lambda: (self.root / "control/paused").exists())
        self.await_condition(lambda: not (self.root / "control/paused").exists())
        before = len(list((self.root / "data").iterdir()))
        self.await_condition(lambda: len(list((self.root / "data").iterdir())) > before)
        self.assertIsNone(self.service.poll())


if __name__ == "__main__":
    unittest.main()

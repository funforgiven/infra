"""Exercise cold-backup ordering and failure recovery without touching a host."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[1] / "backup.sh"


class ColdBackupTests(unittest.TestCase):
    def run_backup(self, failure=""):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        binary = root / "bin"
        binary.mkdir()
        bootstrap = root / "bootstrap"
        bootstrap.mkdir()
        for name in ["repository", "password"]:
            (bootstrap / name).write_text("test-only\n")
        (bootstrap / "environment").write_text("AWS_DEFAULT_REGION=test\n")
        metrics = root / "metrics"
        metrics.mkdir()
        (metrics / "unifi-backup.prom").write_text("old-success\n")
        source = SOURCE.read_text()
        for old, new in {
            "/var/lib/backup-bootstrap": bootstrap,
            "/var/lib/unifi-backup": root / "staging",
            "/var/lib/prometheus/node-exporter": metrics,
            "/run/lock/unifi-backup.lock": root / "lock",
        }.items():
            source = source.replace(old, str(new))
        script = root / "backup.sh"
        script.write_text(source)
        stub = binary / "stub"
        stub.write_text(f'#!{sys.executable}\n' + '''
import json, os, sys
from pathlib import Path
name = Path(sys.argv[0]).name
args = sys.argv[1:]
with open(os.environ['CALLS'], 'a') as stream:
    stream.write(json.dumps([name, *args]) + '\\n')
failure = os.environ['FAILURE']
if name == 'id':
    print('1001')
if name == 'runuser':
    print('true' if failure == 'running' else 'false')
if name == 'tar':
    if failure == 'tar': sys.exit(2)
    Path(args[args.index('-cpf') + 1]).write_text('cold archive')
if name == 'restic' and args[0] == failure:
    sys.exit(1)
''')
        stub.chmod(0o755)
        for name in ["id", "systemctl", "runuser", "tar", "restic"]:
            (binary / name).symlink_to(stub)
        env = {**os.environ, "PATH": f"{binary}:{os.environ['PATH']}",
               "CALLS": str(root / "calls"), "FAILURE": failure}
        result = subprocess.run(["bash", str(script)], env=env, capture_output=True, text=True)
        self.assertTrue((root / "calls").exists(), result.stderr)
        calls = [json.loads(line) for line in (root / "calls").read_text().splitlines()]
        return result, calls, (metrics / "unifi-backup.prom").read_text()

    def test_restart_precedes_offsite_upload_and_success_follows_retention(self):
        result, calls, metric = self.run_backup()
        self.assertEqual(result.returncode, 0, result.stderr)
        stop = calls.index(["systemctl", "stop", "uosserver-updater", "uosserver"])
        archive = next(i for i, call in enumerate(calls) if call[0] == "tar")
        start = calls.index(["systemctl", "start", "uosserver", "uosserver-updater"])
        upload = next(i for i, call in enumerate(calls) if call[:2] == ["restic", "backup"])
        self.assertLess(stop, archive)
        self.assertLess(archive, start)
        self.assertLess(start, upload)
        self.assertTrue(any(call[:2] == ["restic", "forget"] for call in calls))
        self.assertIn("unifi_backup_last_success_timestamp_seconds", metric)

    def test_archive_failure_restarts_controller_and_preserves_last_success(self):
        result, calls, metric = self.run_backup("tar")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(["systemctl", "start", "uosserver", "uosserver-updater"], calls)
        self.assertFalse(any(call[:2] == ["restic", "backup"] for call in calls))
        self.assertEqual(metric, "old-success\n")

    def test_upload_failure_does_not_leave_controller_stopped_or_report_success(self):
        result, calls, metric = self.run_backup("backup")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(["systemctl", "start", "uosserver", "uosserver-updater"], calls)
        self.assertEqual(metric, "old-success\n")

    def test_running_database_refuses_archive(self):
        result, calls, metric = self.run_backup("running")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(any(call[0] == "tar" for call in calls))
        self.assertIn(["systemctl", "start", "uosserver", "uosserver-updater"], calls)
        self.assertEqual(metric, "old-success\n")

    def test_unavailable_repository_does_not_stop_controller(self):
        result, calls, metric = self.run_backup("cat")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(any(call[:2] == ["systemctl", "stop"] for call in calls))
        self.assertEqual(metric, "old-success\n")


if __name__ == "__main__":
    unittest.main()

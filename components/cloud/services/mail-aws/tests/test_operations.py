import email.message
import importlib.util
import json
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("operations", Path(__file__).parents[1] / "operations.py")
ops = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ops)


class MailOperationsTest(unittest.TestCase):
    def test_missing_or_corrupt_success_marker_is_unhealthy(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(ops, "STATE", Path(directory)):
            self.assertGreater(ops.age("backup.json", now=100), 90000)
            Path(directory, "backup.json").write_text('{"last_success": "bad"}')
            self.assertGreater(ops.age("backup.json", now=100), 90000)
            ops.write_state("backup.json", {"last_success": 40})
            self.assertEqual(ops.age("backup.json", now=100), 60)

    def test_canary_requires_matching_identity_and_attachment(self):
        message = email.message.EmailMessage()
        message["Subject"] = "mail-readiness-token"
        message["X-Infra-Probe"] = "mail-readiness-token"
        message.set_content("Synthetic check")
        message.add_attachment(ops.ATTACHMENT, maintype="text", subtype="plain", filename="check.txt")
        ops.verify_canary(message.as_bytes(), "mail-readiness-token")
        with self.assertRaises(ops.OperationError):
            ops.verify_canary(message.as_bytes(), "another-token")
        message.clear_content()
        message.set_content("Matching headers but missing attachment")
        with self.assertRaises(ops.OperationError):
            ops.verify_canary(message.as_bytes(), "mail-readiness-token")

    def test_queue_age_exposes_oldest_stalled_delivery(self):
        self.assertEqual(ops.queue_health([], now=7200), (0, 0))
        self.assertEqual(ops.queue_health([
            {"createdAt": "1970-01-01T01:00:00Z"},
            {"createdAt": "1970-01-01T00:00:00Z"}], now=7200), (2, 7200))

    def test_subprocess_failure_does_not_expose_secret_output(self):
        with patch.object(ops.subprocess, "run", return_value=subprocess.CompletedProcess(
                [], 1, stdout="private mailbox", stderr="private password")):
            with self.assertRaises(ops.OperationError) as error:
                ops.run(["vandelay", "import"])
        self.assertNotIn("private", str(error.exception))

    def test_archive_corruption_fails_verification(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "archive.sqlite")
            with sqlite3.connect(path) as connection:
                connection.execute("CREATE TABLE canary (value TEXT)")
                connection.execute("INSERT INTO canary VALUES ('preserved')")
            ops.validate_archive(path)
            path.write_bytes(b"not a sqlite archive")
            with self.assertRaises(sqlite3.DatabaseError):
                ops.validate_archive(path)

    def test_health_failure_still_publishes_failure_heartbeat(self):
        with patch.object(ops, "age", return_value=10), \
             patch.object(ops.shutil, "disk_usage", return_value=type("Disk", (), {"free": 100})()), \
             patch.object(ops, "run", side_effect=ops.OperationError("service inactive")), \
             patch.object(ops, "metrics") as publish:
            with self.assertRaises(ops.OperationError):
                ops.health()
        self.assertEqual(publish.call_args.args[0]["ServiceHealthy"], 0)

    def test_backup_failure_does_not_advance_last_success(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(ops, "STATE", Path(directory)), \
             patch.object(ops, "SECRETS", Path(directory)), \
             patch.object(ops.shutil, "disk_usage", return_value=type("Disk", (), {"free": 10 ** 12})()), \
             patch.object(ops, "run", side_effect=ops.OperationError("export failed")), \
             patch.object(ops, "metrics") as publish:
            Path(directory, "mailbox-password").write_text("test-value")
            with self.assertRaises(ops.OperationError):
                ops.backup()
            self.assertFalse(Path(directory, "backup.json").exists())
            publish.assert_not_called()

    def test_recovery_manifest_rejects_unexpected_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "manifest.json").write_text(json.dumps({
                "format": 1, "files": {"../../private": "bad"}}))
            with self.assertRaises(ops.OperationError):
                ops.verify_payload(Path(directory))


if __name__ == "__main__":
    unittest.main()

import email.message
import importlib.util
import json
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

SPEC = importlib.util.spec_from_file_location("operations", Path(__file__).parents[1] / "operations.py")
ops = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ops)


class MailOperationsTest(unittest.TestCase):
    def test_admin_policy_scopes_password_api_keys_and_app_passwords_without_replacing_them(self):
        account = {"id": "admin", "roles": {"@type": "Admin"}, "credentials": {
            "0": {"@type": "Password", "otpAuth": "existing MFA", "secret": "existing hash"},
            "2": {"@type": "ApiKey", "secret": "existing key"},
            "5": {"@type": "AppPassword", "secret": "existing app password"}}}
        plans = ops.admin_credential_policy([account, {
            "id": "user", "roles": {"@type": "User"}, "credentials": {"0": {}}}])
        self.assertEqual(len(plans), 1)
        self.assertEqual(plans[0]["id"], "admin")
        self.assertEqual(set(plans[0]["value"]), {
            "credentials/0/allowedIps", "credentials/2/allowedIps", "credentials/5/allowedIps"})
        for allowed in plans[0]["value"].values():
            self.assertEqual(allowed, {"127.0.0.1/32": True, "::1/128": True})
        self.assertNotIn("existing", json.dumps(plans))
        self.assertEqual(account["credentials"]["0"]["otpAuth"], "existing MFA")

    def test_admin_policy_refuses_to_silently_skip_missing_administrators(self):
        for accounts in ([], [{"id": "admin", "roles": {"@type": "Admin"}}]):
            with self.subTest(accounts=accounts), self.assertRaises(ops.OperationError):
                ops.admin_credential_policy(accounts)

    def jmap_canary(self, role="inbox", raw=None):
        message = email.message.EmailMessage()
        message["Subject"] = "mail-readiness-token"
        message["X-Infra-Probe"] = "mail-readiness-token"
        message.set_content("Synthetic check")
        message.add_attachment(ops.ATTACHMENT, maintype="text", subtype="plain", filename="check.txt")
        jmap = Mock()
        jmap.download.return_value = message.as_bytes() if raw is None else raw
        jmap.call.side_effect = [
            {"ids": ["verified-id"]},
            {"list": [{"id": "folder-id", "role": role}]},
            {"list": [{"id": "verified-id", "blobId": "blob", "mailboxIds": {"folder-id": True}}]},
            {"destroyed": ["verified-id"]},
        ]
        return jmap

    def test_jmap_canary_deletes_only_verified_message(self):
        jmap = self.jmap_canary()
        self.assertTrue(ops.receive_canary(jmap, "mail-readiness-token"))
        jmap.call.assert_called_with("Email/set", {"destroy": ["verified-id"]})

    def test_jmap_canary_never_deletes_unverified_content(self):
        jmap = self.jmap_canary(raw=b"Subject: unrelated\r\n\r\nprivate message")
        with self.assertRaises(ops.OperationError):
            ops.receive_canary(jmap, "mail-readiness-token")
        self.assertFalse(any(call.args[0] == "Email/set" for call in jmap.call.call_args_list))

    def test_jmap_canary_rejects_junk_and_non_inbox_delivery(self):
        for role in ("junk", "archive", None):
            with self.subTest(role=role), self.assertRaises(ops.OperationError):
                ops.receive_canary(self.jmap_canary(role=role), "mail-readiness-token")

    def test_jmap_canary_cleanup_failure_is_not_success(self):
        jmap = self.jmap_canary()
        responses = list(jmap.call.side_effect)
        responses[-1] = {"notDestroyed": {"verified-id": {"type": "forbidden"}}}
        jmap.call.side_effect = responses
        with self.assertRaises(ops.OperationError):
            ops.receive_canary(jmap, "mail-readiness-token")

    def test_jmap_credentials_cannot_follow_unsafe_urls(self):
        for url in ("http://mail.fahrican.com/jmap", "https://example.com/jmap",
                    "https://mail.fahrican.com:8443/jmap", "https://user@mail.fahrican.com/jmap"):
            with self.subTest(url=url), self.assertRaises(ops.OperationError):
                ops.jmap_url(url)
        redirect = ops.JmapRedirect()
        with self.assertRaises(ops.OperationError):
            redirect.redirect_request(None, None, 307, "", {}, "https://example.com/private")

    def test_jmap_method_error_does_not_expose_server_details(self):
        jmap = object.__new__(ops.JmapClient)
        jmap.account = "account"
        jmap.session = {"apiUrl": "https://mail.fahrican.com/jmap/"}
        jmap.request = Mock(return_value=json.dumps({"methodResponses": [
            ["error", {"type": "forbidden", "description": "private data"}, "probe"]]}).encode())
        with self.assertRaises(ops.OperationError) as error:
            jmap.call("Mailbox/get", {})
        self.assertNotIn("private", str(error.exception))

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

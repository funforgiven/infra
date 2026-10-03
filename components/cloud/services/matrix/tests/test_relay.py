from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from relay import Queue, authenticate, check_room, messages
from notify_host import notify


class QueueTests(unittest.TestCase):
    def test_restart_and_ambiguous_delivery_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "queue.sqlite"
            first = Queue(path)
            key = first.put("host", "invocation", "failure")
            first.db.close()
            recovered = Queue(path)
            self.assertEqual(recovered.pending(), (key, "failure"))
            self.assertEqual(recovered.put("host", "invocation", "failure"), key)
            with self.assertRaises(ValueError):
                recovered.put("host", "invocation", "different")
            recovered.snapshot(Path(directory) / "snapshot.sqlite")
            self.assertEqual(
                Queue(Path(directory) / "snapshot.sqlite").pending(), (key, "failure")
            )
            recovered.delivered(key)
            recovered.put("host", "invocation", "failure")
            self.assertIsNone(recovered.pending())

    def test_authentication_is_scoped(self):
        producers = {"host": {"token": "secret", "paths": ["/notify"]}}
        self.assertEqual(authenticate("Bearer secret", producers, "/notify"), "host")
        self.assertIsNone(authenticate("Bearer secret", producers, "/alertmanager"))
        self.assertIsNone(authenticate("Bearer wrong", producers, "/notify"))

    def test_conflicting_batch_rolls_back_and_delivery_erases_body(self):
        with tempfile.TemporaryDirectory() as directory:
            queue = Queue(Path(directory) / "queue.sqlite")
            key = queue.put("host", "existing", "original")
            with self.assertRaises(ValueError):
                queue.put_many("host", [("new", "new body"), ("existing", "changed")])
            self.assertEqual(queue.stats()[0], 1)
            queue.delivered(key)
            self.assertEqual(
                queue.db.execute(
                    "SELECT body FROM events WHERE id=?", (key,)
                ).fetchone(),
                ("",),
            )

    def test_producer_cannot_impersonate_another(self):
        with self.assertRaises(ValueError):
            messages({"producer_id": "other"}, "host", "/notify")

    def test_resolved_notification_has_distinct_transaction(self):
        alert = {
            "fingerprint": "abc",
            "startsAt": "2026-10-03",
            "labels": {},
            "status": "firing",
        }
        firing = messages({"alerts": [alert]}, "alertmanager", "/alertmanager")
        resolved = messages(
            {"alerts": [dict(alert, status="resolved", endsAt="later")]},
            "alertmanager",
            "/alertmanager",
        )
        self.assertNotEqual(firing[0][0], resolved[0][0])


class EncryptionTests(unittest.TestCase):
    def test_plaintext_room_and_unapproved_devices_fail_closed(self):
        client = MagicMock()
        room = MagicMock(encrypted=False, users={"@owner:local": object()})
        client.rooms = {"!room:local": room}
        with self.assertRaises(ValueError):
            check_room(client, "!room:local", ["@owner:local"], {})
        room.encrypted = True
        device = MagicMock(id="PHONE", ed25519="fingerprint")
        client.device_store.active_user_devices.return_value = [device]
        with self.assertRaises(ValueError):
            check_room(client, "!room:local", ["@owner:local"], {})
        client.verify_device.assert_not_called()
        check_room(
            client,
            "!room:local",
            ["@owner:local"],
            {"@owner:local": {"PHONE": "fingerprint"}},
        )
        client.verify_device.assert_called_once_with(device)
        with self.assertRaises(ValueError):
            check_room(client, "!room:local", [], {})


class HostTests(unittest.TestCase):
    def test_unavailable_relay_uses_independent_tls_email(self):
        config = {
            "url": "https://matrix.fahrican.com/internal/notify",
            "token": "secret",
            "producer_id": "host",
            "smtp": {
                "host": "mail.fahrican.com",
                "username": "alerts",
                "password": "secret",
                "from": "alerts@fahrican.com",
                "to": "owner@example.com",
            },
        }
        with (
            patch("urllib.request.urlopen", side_effect=OSError),
            patch("smtplib.SMTP_SSL") as smtp,
        ):
            notify(config, "backup.service")
            smtp.return_value.__enter__.return_value.send_message.assert_called_once()


if __name__ == "__main__":
    unittest.main()

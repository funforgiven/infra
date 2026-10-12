import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE))
SPEC = importlib.util.spec_from_file_location("netbird_admin", SOURCE / "admin.py")
admin = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(admin)


class BootstrapTests(unittest.TestCase):
    def test_invalid_account_identifier_never_reaches_database(self):
        with patch.object(admin, "run") as run:
            with self.assertRaisesRegex(ValueError, "account identifier"):
                admin.bind_bootstrap_account("unexpected'; DELETE FROM accounts;")
            run.assert_not_called()

    def test_local_owner_and_automation_are_not_sso_qualification(self):
        users = [
            {"id": "bootstrap", "is_service_user": False, "idp_id": "local"},
            {"id": "another-local-user", "is_service_user": False, "idp_id": "local"},
            {"id": "automation", "is_service_user": True},
        ]
        self.assert_closure_rejected(users)

    def test_blocked_or_unapproved_sso_user_cannot_close_bootstrap(self):
        for state in ({"is_blocked": True}, {"pending_approval": True}):
            with self.subTest(state=state):
                self.assert_closure_rejected([
                    {"id": "sso", "is_service_user": False, "idp_id": "zitadel-test", **state},
                ])

    def assert_closure_rejected(self, users):
        state = {"owner_id": "bootstrap", "tofu-netbird": {"plain_token": "synthetic"}}
        with patch.object(admin, "decrypt", return_value=state), \
             patch.object(admin, "api", return_value=users), \
             patch.object(admin, "encrypt") as encrypt:
            with self.assertRaisesRegex(ValueError, "approved SSO user"):
                admin.close_bootstrap()
            encrypt.assert_not_called()


if __name__ == "__main__":
    unittest.main()

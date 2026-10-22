import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

SOURCE = Path(__file__).resolve().parents[1]
ROOT = SOURCE.parents[3]
sys.path.insert(0, str(SOURCE.parents[1] / "operations"))
SPEC = importlib.util.spec_from_file_location("netbird_admin", SOURCE / "admin.py")
admin = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(admin)


class RotationTests(unittest.TestCase):
    def test_new_tokens_are_saved_before_publication_and_old_tokens_survive(self):
        state = {
            "default_policy_id": "policy",
            "tofu-netbird": {"user_id": "tofu", "plain_token": "old-tofu"},
            "kubernetes-netbird": {"user_id": "kube", "plain_token": "old-kube"},
        }
        token = {"personal_access_token": {"expiration_date": "2027-10-23T00:00:00+00:00"}}
        calls = []
        with tempfile.TemporaryDirectory() as directory:
            deployment = Path(directory)
            (deployment / "operator").mkdir()
            (deployment / "server").mkdir()
            operator = ROOT / "deployments/homelab/cluster/apps/netbird/operator/operator.yaml"
            (deployment / "operator/operator.yaml").write_text(operator.read_text())
            with (
                patch.object(admin, "DEPLOYMENT", deployment),
                patch.object(admin, "decrypt", return_value=state),
                patch.object(admin, "api", side_effect=lambda *a: dict(token, plain_token="new-" + a[2])),
                patch.object(admin, "encrypt", side_effect=lambda path, doc: calls.append(path)),
            ):
                admin.rotate_credentials()
            rules = yaml.safe_load((deployment / "server/credentials-monitoring.yaml").read_text())
        self.assertEqual(calls[:2], [admin.BOOTSTRAP, admin.BOOTSTRAP])
        self.assertEqual(state["tofu-netbird"]["plain_token"], "new-old-tofu")
        self.assertEqual(len(rules["spec"]["groups"][0]["rules"]), 2)


if __name__ == "__main__":
    unittest.main()

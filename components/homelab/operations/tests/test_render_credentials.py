import base64
import copy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import render_credentials as credentials


class CredentialRefresh(unittest.TestCase):
    def outputs(self):
        return {app + "_client_" + field: {"value": "new-" + app + "-" + field}
                for app in credentials.OIDC_APPS for field in ("id", "secret")}

    def test_missing_outputs_fail_before_decryption_or_writes(self):
        outputs = self.outputs()
        del outputs["matrix_client_secret"]
        with patch.object(credentials, "decrypt") as decrypt, patch.object(credentials, "save") as save:
            with self.assertRaises(ValueError): credentials.render(Path("/test"), outputs)
            decrypt.assert_not_called()
            save.assert_not_called()

    def test_refresh_preserves_signing_keys_other_providers_and_metadata(self):
        mas = {"secrets": {"encryption": "existing-session-key"}, "upstream_oauth2": {"providers": [
            {"issuer": "https://other.example", "client_id": "other-id", "client_secret": "other-secret"},
            {"issuer": "https://auth.cloud.fahrican.com/", "client_id": "old", "client_secret": "old-secret"},
        ]}}
        forge = {"kind": "Secret", "metadata": {"name": "forge-runtime", "labels": {"keep": "yes"}},
                 "data": {"forgejo-secret-key": base64.b64encode(b"existing-signing-key").decode()}}
        matrix = {"kind": "Secret", "metadata": {"name": "matrix-runtime"},
                  "stringData": {"mas.yaml": yaml.safe_dump(mas), "signing.key": "existing-matrix-key"}}
        netbird = {"kind": "Secret", "metadata": {"name": "identity"}, "stringData": {"extra": "preserved"}}
        sources = {"forge": [forge], "matrix": [matrix], "netbird-policy": [netbird]}
        written = {}
        def decrypt(path):
            return copy.deepcopy(next(value for key, value in sources.items() if key in str(path)))
        with patch.object(credentials, "decrypt", side_effect=decrypt):
            credentials.update_identity(Path("/test"), self.outputs(), lambda path, docs: written.update({path: docs}))
        result = written["deployments/homelab/cluster/apps/forge/runtime.sops.yaml"][0]
        self.assertEqual(result["stringData"]["forgejo-secret-key"], "existing-signing-key")
        self.assertEqual(result["metadata"]["labels"], {"keep": "yes"})
        result = written["deployments/homelab/cluster/apps/matrix/runtime.sops.yaml"][0]
        self.assertEqual(result["stringData"]["signing.key"], "existing-matrix-key")
        config = yaml.safe_load(result["stringData"]["mas.yaml"])
        self.assertEqual(config["secrets"], mas["secrets"])
        self.assertEqual(config["upstream_oauth2"]["providers"][0], mas["upstream_oauth2"]["providers"][0])
        self.assertEqual(config["upstream_oauth2"]["providers"][1]["client_id"], "new-matrix-id")
        self.assertEqual(written["deployments/homelab/credentials/netbird-policy/identity.sops.yaml"][0]["stringData"]["extra"], "preserved")

    def test_ambiguous_matrix_identity_refuses_rewrite(self):
        outputs = self.outputs()
        forge = {"metadata": {"name": "forge-runtime"}, "stringData": {}}
        matrix = {"metadata": {"name": "matrix-runtime"}, "stringData": {"mas.yaml": yaml.safe_dump({
            "upstream_oauth2": {"providers": [{"issuer": "https://other.example"}]}})}}
        with patch.object(credentials, "decrypt", side_effect=[[forge], [matrix]]):
            with self.assertRaises(ValueError):
                credentials.update_identity(Path("/test"), outputs, lambda path, docs: None)


if __name__ == "__main__": unittest.main()

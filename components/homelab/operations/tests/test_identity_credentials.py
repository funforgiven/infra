import base64
import copy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import identity_credentials as credentials


class IdentityCredentials(unittest.TestCase):
    def outputs(self):
        return {app + "_client_" + field: {"value": "new-" + app + "-" + field}
                for app in credentials.OIDC_APPS for field in ("id", "secret")}

    def sources(self):
        mas = {"secrets": {"encryption": "existing-session-key"}, "upstream_oauth2": {"providers": [
            {"issuer": "https://other.example", "client_id": "other-id", "client_secret": "other-secret"},
            {"issuer": "https://auth.cloud.fahrican.com/", "client_id": "old", "client_secret": "old-secret"},
        ]}}
        return mas, {
            # Like the real file: values in both stringData and data.
            "forge": [{"kind": "Secret", "metadata": {"name": "forge-runtime", "labels": {"keep": "yes"}},
                       "stringData": {"forgejo-oidc-client-id": "old"},
                       "data": {"forgejo-secret-key": base64.b64encode(b"existing-signing-key").decode()}}],
            "matrix": [{"kind": "Secret", "metadata": {"name": "matrix-runtime"},
                        "stringData": {"mas.yaml": yaml.safe_dump(mas), "signing.key": "existing-matrix-key"}}],
            "media": [{"metadata": {"name": "media-runtime"}, "stringData": {"ND_LASTFM_APIKEY": "kept"}},
                      {"metadata": {"name": "discord-music-runtime"}, "stringData": {"DISCORD_TOKEN": "kept"}}],
            "observability": [{"metadata": {"name": "infrastructure-telegram"}, "stringData": {"bot-token": "kept"}},
                              {"metadata": {"name": "grafana-oidc"}, "data": {
                                  "GF_AUTH_GENERIC_OAUTH_CLIENT_ID": base64.b64encode(b"old").decode()}}],
        }

    def render(self, outputs, sources):
        written = {}
        def decrypt(path):
            return copy.deepcopy(next(value for key, value in sources.items() if "/" + key + "/" in str(path)))
        with patch.object(credentials, "decrypt", side_effect=decrypt), \
             patch.object(credentials, "save", side_effect=lambda root, path, docs: written.update({path: docs}) or True):
            changed = credentials.render(Path("/test"), outputs)
        return changed, written

    def test_missing_outputs_fail_before_decryption_or_writes(self):
        outputs = self.outputs()
        del outputs["matrix_client_secret"]
        with patch.object(credentials, "decrypt") as decrypt, patch.object(credentials, "save") as save:
            with self.assertRaises(ValueError):
                credentials.render(Path("/test"), outputs)
            decrypt.assert_not_called()
            save.assert_not_called()

    def test_updates_clients_and_preserves_other_values(self):
        mas, sources = self.sources()
        changed, written = self.render(self.outputs(), sources)
        self.assertEqual(len(changed), 4)
        forge = written["deployments/homelab/cluster/apps/forge/runtime.sops.yaml"][0]
        self.assertEqual(forge["stringData"]["forgejo-secret-key"], "existing-signing-key")
        self.assertEqual(forge["stringData"]["forgejo-oidc-client-id"], "new-forgejo-id")
        self.assertEqual(forge["metadata"]["labels"], {"keep": "yes"})
        matrix = written["deployments/homelab/cluster/apps/matrix/runtime.sops.yaml"][0]
        self.assertEqual(matrix["stringData"]["signing.key"], "existing-matrix-key")
        config = yaml.safe_load(matrix["stringData"]["mas.yaml"])
        self.assertEqual(config["secrets"], mas["secrets"])
        self.assertEqual(config["upstream_oauth2"]["providers"][0], mas["upstream_oauth2"]["providers"][0])
        self.assertEqual(config["upstream_oauth2"]["providers"][1]["client_secret"], "new-matrix-secret")
        media = written["deployments/homelab/cluster/apps/media/runtime.sops.yaml"]
        self.assertEqual(media[0]["stringData"]["ND_LASTFM_APIKEY"], "kept")
        self.assertEqual(media[0]["stringData"]["AUDIOMUSE_OIDC_CLIENT_SECRET"], "new-audiomuse-secret")
        self.assertEqual(media[1]["stringData"], {"DISCORD_TOKEN": "kept"})
        observability = written["deployments/homelab/cluster/infrastructure/observability/runtime.sops.yaml"]
        self.assertEqual(observability[0]["stringData"], {"bot-token": "kept"})
        self.assertEqual(observability[1]["stringData"]["GF_AUTH_GENERIC_OAUTH_CLIENT_ID"], "new-grafana-id")
        self.assertNotIn("data", observability[1])

    def test_ambiguous_matrix_identity_refuses_rewrite(self):
        _, sources = self.sources()
        sources["matrix"][0]["stringData"]["mas.yaml"] = yaml.safe_dump(
            {"upstream_oauth2": {"providers": [{"issuer": "https://other.example"}]}})
        with self.assertRaises(ValueError):
            self.render(self.outputs(), sources)


if __name__ == "__main__":
    unittest.main()

"""Check generated runtime credentials against the registry chart's YAML merge."""

import base64
import json
from pathlib import Path
import textwrap
import unittest
from unittest.mock import patch

import yaml


class RuntimeTests(unittest.TestCase):
    def test_registry_storage_can_be_extended_by_chart(self):
        repo = Path(__file__).resolve().parents[5]
        manifest = repo / "deployments/homelab/cloud/undercloud/88-gitlab-cluster/reconcile.yaml"
        config = next(item for item in yaml.safe_load_all(manifest.read_text())
                      if item["kind"] == "ConfigMap")
        # Deliberately exercise quoting, colons and escapes in credential values.
        credential = 'test: "quoted" \\ value # not a comment'
        rgw = json.dumps({"data": {key: base64.b64encode(credential.encode()).decode()
                                  for key in ("AccessKey", "SecretKey")}})
        outputs = {}

        class InputPath:
            def __init__(self, name):
                self.name = name

            def read_text(self):
                return rgw if self.name == "/tmp/rgw.json" else credential

            def write_text(self, value):
                outputs[self.name] = value

        with patch("pathlib.Path", InputPath):
            exec(compile(config["data"]["render-runtime.py"], str(manifest), "exec"), {})
        secrets = json.loads(outputs["/tmp/gitlab-runtime.json"])["items"]
        storage = next(item["stringData"] for item in secrets
                       if item["metadata"]["name"] == "gitlab-object-storage")
        # The registry init script inserts the fragment under storage, then
        # appends delete.enabled before the chart's own maintenance settings.
        merged = ("storage:\n" + textwrap.indent(storage["registry"], "  ")
                  + "  delete:\n    enabled: true\n"
                  + "  maintenance:\n    readonly:\n      enabled: false\n")
        parsed = yaml.safe_load(merged)["storage"]
        self.assertEqual(parsed["s3_v2"]["secretkey"], credential)
        self.assertTrue(parsed["s3_v2"]["pathstyle"])
        self.assertTrue(parsed["redirect"]["disable"])
        self.assertTrue(parsed["delete"]["enabled"])
        self.assertFalse(parsed["maintenance"]["readonly"]["enabled"])


if __name__ == "__main__":
    unittest.main()

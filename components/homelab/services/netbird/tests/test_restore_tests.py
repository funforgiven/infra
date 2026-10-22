"""The CloudNativePG restore tests share one script and never write archives."""
import unittest
from pathlib import Path

import yaml

APPS = Path(__file__).resolve().parents[5] / "deployments/homelab/cluster/apps"
SOURCES = {
    "identity": APPS / "identity/database/restore-test.yaml",
    "netbird": APPS / "netbird/server/restore-test.yaml",
    "matrix": APPS / "matrix/restore-test.yaml",
}


def documents(path):
    return [d for d in yaml.safe_load_all(path.read_text()) if d]


class RestoreTestTests(unittest.TestCase):
    def test_one_script_for_every_database(self):
        scripts = {
            app: next(d for d in documents(path) if d["kind"] == "ConfigMap")["data"]["run.sh"]
            for app, path in SOURCES.items()
        }
        self.assertEqual(len(set(scripts.values())), 1)

    def test_recovered_cluster_is_isolated_and_read_only(self):
        for app, path in SOURCES.items():
            with self.subTest(app=app):
                objects = documents(path)
                namespace = app + "-restore"
                config = next(d for d in objects if d["kind"] == "ConfigMap")
                cluster = yaml.safe_load(config["data"]["cluster.yaml"])
                self.assertEqual(cluster["metadata"]["namespace"], namespace)
                self.assertNotIn("plugins", cluster["spec"])
                self.assertNotIn("backup", cluster["spec"])
                self.assertIn("recovery", cluster["spec"]["bootstrap"])
                deny = next(d for d in objects if d["metadata"]["name"] == "default-deny")
                self.assertEqual(deny["metadata"]["namespace"], namespace)
                self.assertEqual(deny["spec"], {"podSelector": {}, "policyTypes": ["Ingress", "Egress"]})
                store = next(d for d in objects if d["kind"] == "ObjectStore")
                self.assertNotIn("retentionPolicy", store["spec"])
                # Production namespaces only grant reading the one archive credential.
                grants = [d for d in objects if d["kind"] == "Role" and d["metadata"]["namespace"] != namespace]
                self.assertEqual(len(grants), 1)
                self.assertEqual(grants[0]["rules"], [{
                    "apiGroups": [""], "resources": ["secrets"],
                    "resourceNames": grants[0]["rules"][0]["resourceNames"], "verbs": ["get"],
                }])
                self.assertEqual(len(grants[0]["rules"][0]["resourceNames"]), 1)


if __name__ == "__main__":
    unittest.main()

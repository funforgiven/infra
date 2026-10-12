from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import database_bootstrap


def obj(kind, name, spec=None):
    result = {"apiVersion": "v1", "kind": kind, "metadata": {"namespace": "matrix", "name": name}}
    if spec is not None: result["spec"] = spec
    return result


class DatabaseBootstrap(unittest.TestCase):
    def source(self):
        return [obj("Service", "matrix-postgres", {}),
                obj("StatefulSet", "matrix-postgres", {"replicas": 1, "template": {"spec": {
                    "containers": [{"name": "postgres", "image": "registry/runtime@sha256:pinned",
                                    "env": [{"name": "PASSWORD", "valueFrom": {"secretKeyRef": {"name": "runtime", "key": "password"}}}]}],
                    "volumes": [{"persistentVolumeClaim": {"claimName": "data"}}, {"configMap": {"name": "scripts-hash"}}],
                    "imagePullSecrets": [{"name": "registry"}],
                }}}), obj("PersistentVolumeClaim", "data", {"storageClassName": "ceph-block"}),
                obj("Secret", "runtime"), obj("Secret", "registry"), obj("ConfigMap", "scripts-hash"),
                obj("Deployment", "matrix-synapse", {}), obj("CronJob", "backup", {}),
                obj("PersistentVolumeClaim", "matrix-media", {})]

    def test_only_database_writer_and_required_dependencies_are_selected(self):
        result = database_bootstrap.select(self.source(), "matrix")
        self.assertEqual({d["kind"] for d in result}, {"Service", "StatefulSet", "PersistentVolumeClaim", "Secret", "ConfigMap"})
        writers = [d for d in result if d["kind"] == "StatefulSet"]
        self.assertEqual(len(writers), 1)
        self.assertEqual(writers[0]["spec"]["template"]["spec"]["containers"][0]["image"], "registry/runtime@sha256:pinned")
        self.assertNotIn("matrix-media", [d["metadata"]["name"] for d in result])
        self.assertIn("scripts-hash", [d["metadata"]["name"] for d in result])

    def test_missing_dependency_and_rebound_source_claim_are_refused(self):
        source = self.source()
        with self.assertRaises(ValueError): database_bootstrap.select([d for d in source if d["metadata"]["name"] != "registry"], "matrix")
        source[2]["spec"]["volumeName"] = "source-cinder-pv"
        with self.assertRaises(ValueError): database_bootstrap.select(source, "matrix")


if __name__ == "__main__": unittest.main()

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / "apply_policy.py"
spec = importlib.util.spec_from_file_location("worker_policy", SOURCE)
policy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(policy)
CONFIG = "apiVersion: kubelet.config.k8s.io/v1beta1\nkind: KubeletConfiguration\nclusterDNS:\n- 10.254.0.10\nauthentication:\n  anonymous:\n    enabled: false\n"
ROTATION = "/var/log/syslog\n/var/log/auth.log\n{\n\trotate 4\n\tweekly\n\tmissingok\n\tcompress\n\tdelaycompress\n\tpostrotate\n\t\t/usr/lib/rsyslog/rsyslog-rotate\n\tendscript\n}\n"


class WorkerPolicyTests(unittest.TestCase):
    def test_yaml_preserves_authentication_and_dns_and_is_idempotent(self):
        output = policy.kubelet_policy(CONFIG)
        self.assertTrue(output.startswith(CONFIG))
        self.assertIn("imageGCHighThresholdPercent: 70\n", output)
        self.assertIn("imageGCLowThresholdPercent: 60\n", output)
        self.assertEqual(output, policy.kubelet_policy(output))

    def test_json_and_more_conservative_limits_are_preserved(self):
        data = {
            "apiVersion": "kubelet.config.k8s.io/v1beta1",
            "kind": "KubeletConfiguration",
            "authentication": {"anonymous": {"enabled": False}},
        }
        output = json.loads(policy.kubelet_policy(json.dumps(data)))
        self.assertEqual(data["authentication"], output["authentication"])
        text = (
            CONFIG + "imageGCHighThresholdPercent: 60\nimageGCLowThresholdPercent: 50\n"
        )
        self.assertEqual(text, policy.kubelet_policy(text))

    def test_invalid_and_duplicate_thresholds_fail_before_mutation(self):
        for suffix in (
            "imageGCHighThresholdPercent: 70\nimageGCHighThresholdPercent: 80\n",
            "imageGCHighThresholdPercent: 40\nimageGCLowThresholdPercent: 50\n",
            "imageGCLowThresholdPercent: invalid\n",
        ):
            with self.subTest(suffix=suffix), self.assertRaises(ValueError):
                policy.kubelet_policy(CONFIG + suffix)
        with self.assertRaises(ValueError):
            policy.kubelet_policy(
                CONFIG.replace("KubeletConfiguration", "OtherConfiguration")
            )

    def test_rotation_keeps_log_paths_and_reopen_hook(self):
        output = policy.rsyslog_policy(ROTATION)
        self.assertEqual(ROTATION.split("{")[0], output.split("{")[0])
        self.assertIn("/usr/lib/rsyslog/rsyslog-rotate", output)
        self.assertIn("maxsize 64M", output)
        self.assertIn("su root adm", output)
        self.assertIn("\n\tcreate\n", output)
        self.assertNotIn("delaycompress", output)
        self.assertEqual(output, policy.rsyslog_policy(output))
        with self.assertRaises(ValueError):
            policy.rsyslog_policy(ROTATION.replace("rotate 4", "rotate 20"))

    def test_host_command_failure_restores_all_configuration_and_file_modes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            policy.write(root / policy.KUBELET, CONFIG, 0o600)
            policy.write(root / policy.RSYSLOG, ROTATION)
            with (
                patch.object(
                    policy.subprocess, "run", side_effect=RuntimeError("injected")
                ),
                self.assertRaisesRegex(RuntimeError, "previous configuration restored"),
            ):
                policy.apply(root)
            self.assertEqual(CONFIG, (root / policy.KUBELET).read_text())
            self.assertEqual(0o600, (root / policy.KUBELET).stat().st_mode & 0o777)
            self.assertEqual(ROTATION, (root / policy.RSYSLOG).read_text())
            self.assertFalse((root / policy.JOURNAL).exists())
            self.assertFalse((root / policy.TIMER).exists())

    def test_control_planes_are_rejected_without_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "etc/kubernetes/manifests/kube-apiserver.yaml"
            manifest.parent.mkdir(parents=True)
            manifest.touch()
            with self.assertRaisesRegex(ValueError, "control plane"):
                policy.apply(root)
            self.assertFalse((root / policy.STATE).exists())


if __name__ == "__main__":
    unittest.main()

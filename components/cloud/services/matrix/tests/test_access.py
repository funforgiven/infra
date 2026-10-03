import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import access


class AccessTests(unittest.TestCase):
    def exercise(self, failure=False):
        descriptor = os.memfd_create("test-undercloud")
        os.write(descriptor, b"test-kubeconfig")
        original_temporary_directory = tempfile.TemporaryDirectory
        directories = []

        def temporary_directory(**kwargs):
            directory = original_temporary_directory(prefix=kwargs["prefix"])
            directories.append(Path(directory.name))
            return directory

        def capture(command, **kwargs):
            if command[0] == "kubectl":
                self.assertEqual(Path(command[2]).read_bytes(), b"test-kubeconfig")
                return json.dumps(
                    {
                        "data": {
                            "OS_PASSWORD": base64.b64encode(
                                b"provider-password"
                            ).decode()
                        }
                    }
                ).encode()
            self.assertEqual(command[0], "openstack")
            environment = kwargs["env"]
            self.assertEqual(environment["OS_PASSWORD"], "provider-password")
            self.assertEqual(environment["OS_PROJECT_NAME"], "services")
            self.assertEqual(environment["OS_INTERFACE"], "public")
            self.assertEqual(
                environment["OS_AUTH_URL"], "https://identity.cloud.fahrican.com/v3"
            )
            self.assertNotIn("OS_PROJECT_ID", environment)
            if failure:
                raise subprocess.CalledProcessError(1, command)
            (directories[0] / "config").write_text("test-services-config")
            return b""

        def run(command, **kwargs):
            self.assertEqual(command, ["kubectl", "get", "nodes"])
            environment = kwargs["env"]
            self.assertNotIn("OS_PASSWORD", environment)
            self.assertEqual(
                Path(environment["KUBECONFIG"]).read_text(), "test-services-config"
            )
            return subprocess.CompletedProcess(command, 0)

        with (
            patch.object(access, "undercloud_config", return_value=descriptor),
            patch.object(access, "capture", side_effect=capture),
            patch.object(
                access.tempfile, "TemporaryDirectory", side_effect=temporary_directory
            ),
            patch.object(access.subprocess, "run", side_effect=run),
            patch.dict(os.environ, {"OS_PROJECT_ID": "stale-project"}),
        ):
            if failure:
                with self.assertRaises(subprocess.CalledProcessError):
                    access.execute("services", ["kubectl", "get", "nodes"])
            else:
                self.assertEqual(
                    access.execute("services", ["kubectl", "get", "nodes"]), 0
                )
        self.assertFalse(directories[0].exists())
        with self.assertRaises(OSError):
            os.fstat(descriptor)

    def test_provider_credentials_are_scoped_and_kubeconfig_is_removed(self):
        self.exercise()

    def test_failure_also_closes_memory_config_and_removes_directory(self):
        self.exercise(failure=True)

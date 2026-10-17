import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import access

class AccessTests(unittest.TestCase):
    def exercise(self, failure=False):
        descriptor = os.memfd_create("test-cluster")
        os.write(descriptor, b"administrator-credential")
        original_temporary_directory = tempfile.TemporaryDirectory
        directories = []
        def temporary_directory(**kwargs):
            directory = original_temporary_directory(prefix=kwargs["prefix"])
            directories.append(Path(directory.name))
            return directory
        def run(command, **kwargs):
            environment = kwargs["env"]
            self.assertEqual(Path(environment["KUBECONFIG"]).read_bytes(), b"administrator-credential")
            self.assertEqual(environment.get("HOME"), os.environ.get("HOME"))
            self.assertEqual(command[-2:], ["get", "nodes"])
            self.assertIn("--cache-dir", command)
            self.assertFalse(any(p.is_file() for p in directories[0].rglob("*")))
            if failure: raise subprocess.CalledProcessError(1, command)
            return subprocess.CompletedProcess(command, 0)
        with patch.object(access, "cluster_config", return_value=descriptor), patch.object(access.tempfile, "TemporaryDirectory", side_effect=temporary_directory), patch.object(access.subprocess, "run", side_effect=run):
            if failure:
                with self.assertRaises(subprocess.CalledProcessError): access.execute("cluster", ["kubectl", "get", "nodes"])
            else: self.assertEqual(access.execute("cluster", ["kubectl", "get", "nodes"]), 0)
        self.assertFalse(directories[0].exists())
        with self.assertRaises(OSError): os.fstat(descriptor)
    def test_success_closes_administrator_config_and_cache(self): self.exercise()
    def test_child_failure_closes_administrator_config_and_cache(self): self.exercise(True)
    def test_removed_cluster_names_are_rejected_before_access(self):
        with patch.object(access, "cluster_config") as config:
            with self.assertRaises(ValueError): access.execute("retired", ["kubectl", "get", "nodes"])
            config.assert_not_called()
    def test_unreachable_server_falls_back_to_the_next(self):
        calls = []
        def capture(command, **kwargs):
            calls.append(command[-2])
            if len(calls) == 1: raise subprocess.CalledProcessError(255, command)
            return b"config"
        with patch.object(access, "capture", side_effect=capture):
            self.assertEqual(access.read_admin_config(), b"config")
        self.assertEqual(calls, ["funforgiven@10.21.20.10", "funforgiven@10.21.20.11"])

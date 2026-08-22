from pathlib import Path
from tempfile import TemporaryDirectory
import os
import subprocess
import unittest
from unittest.mock import patch

import yaml

from aws_mail_credentials import (
    AUTH_KEYS,
    BOOTSTRAP_KEYS,
    GITOPS_POLICY_FILE,
    RESEND_FILE,
    RESEND_KEY,
    AwsMailCredentialError,
    AwsMailCredentials,
)
from runtime_contract import CONTRACT_PATH


AWS_FILE = Path("deployments/aws.sops.yaml")


class FakeStore:
    def __init__(self) -> None:
        self.writes: list[tuple[Path, dict[str, str]]] = []
        self.values: dict[tuple[Path, str], str] = {}

    def write(self, path: Path, values: dict[str, str]) -> None:
        self.writes.append((path, dict(values)))
        self.values.update({(path, key): value for key, value in values.items()})

    def read(self, path: Path, key: str) -> str | None:
        return self.values.get((path, key))


class AwsMailCredentialsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        contract = {
            "schemaVersion": 8,
            "secretFile": "cluster.sops.yaml",
            "credentials": {"cluster": ["CLUSTER_KEY"]},
            "hostCredentials": {
                "host": {"secretFile": "host.sops.yaml", "keys": ["HOST_KEY"]}
            },
            "generatedSecrets": {
                "local": {
                    "secretFile": "generated.sops.yaml",
                    "keys": ["GENERATED_KEY"],
                }
            },
            "provisionedSecrets": {
                "aws-mail-auth": {
                    "provisioner": "enroll-aws-mail-auth",
                    "secretFile": str(AWS_FILE),
                    "keys": list(AUTH_KEYS),
                }
            },
        }
        path = self.root / CONTRACT_PATH
        path.parent.mkdir(parents=True)
        path.write_text(
            yaml.safe_dump({"data": {"required-keys.yaml": yaml.safe_dump(contract)}}),
            encoding="utf-8",
        )
        intake = self.root / "secrets"
        intake.mkdir()
        policy_path = self.root / GITOPS_POLICY_FILE
        policy_path.parent.mkdir(parents=True)
        policy_path.write_text(
            '{"Version":"2012-10-17","Account":"ACCOUNT_ID"}',
            encoding="utf-8",
        )
        self.bootstrap_access_id = "AKIA" + "A" * 16
        self.bootstrap_secret = "a" * 40
        self.access_id = "AKIA" + "B" * 16
        self.secret = "b" * 40
        self.assertEqual(len(self.secret), 40)
        for key, value in zip(
            BOOTSTRAP_KEYS,
            (self.bootstrap_access_id, self.bootstrap_secret),
            strict=True,
        ):
            key_file = intake / f"{key}.key"
            key_file.write_text(value + "\n", encoding="ascii")
            key_file.chmod(0o600)
        self.credentials = AwsMailCredentials(self.root)
        self.store = FakeStore()
        self.credentials.store = self.store

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    @patch.object(AwsMailCredentials, "_reconcile_gitops_identity")
    def test_enrollment_writes_one_destination_then_clears_intake(
        self, reconcile
    ) -> None:
        reconcile.return_value = {
            AUTH_KEYS[0]: self.access_id,
            AUTH_KEYS[1]: self.secret,
        }
        self.credentials.enroll_provisioning()
        reconcile.assert_called_once_with(
            {
                BOOTSTRAP_KEYS[0]: self.bootstrap_access_id,
                BOOTSTRAP_KEYS[1]: self.bootstrap_secret,
            }
        )
        self.assertEqual(
            self.store.writes,
            [(AWS_FILE, {AUTH_KEYS[0]: self.access_id, AUTH_KEYS[1]: self.secret})],
        )
        for key in BOOTSTRAP_KEYS:
            self.assertEqual((self.root / "secrets" / f"{key}.key").stat().st_size, 0)

    def test_invalid_permissions_are_rejected_without_clearing(self) -> None:
        key_file = self.root / "secrets" / f"{BOOTSTRAP_KEYS[0]}.key"
        key_file.chmod(0o644)
        with self.assertRaisesRegex(AwsMailCredentialError, "mode 0600"):
            self.credentials.enroll_provisioning()
        self.assertEqual(self.store.writes, [])
        self.assertGreater(key_file.stat().st_size, 0)

    @patch("aws_mail_credentials.subprocess.run")
    def test_resend_publication_uses_stdin_and_suppresses_output(self, run) -> None:
        for key, value in zip(AUTH_KEYS, (self.access_id, self.secret), strict=True):
            self.store.values[(AWS_FILE, key)] = value
        self.store.values[(RESEND_FILE, RESEND_KEY)] = "re_private-value-not-output"
        run.return_value = subprocess.CompletedProcess([], 0)

        self.credentials.publish_resend()

        arguments, options = run.call_args
        self.assertEqual(options["input"], "re_private-value-not-output")
        self.assertEqual(options["stdout"], subprocess.DEVNULL)
        self.assertEqual(options["stderr"], subprocess.DEVNULL)
        self.assertNotIn("re_private-value-not-output", arguments[0])
        self.assertEqual(options["env"][AUTH_KEYS[0]], self.access_id)
        self.assertEqual(options["env"][AUTH_KEYS[1]], self.secret)

    @patch.object(AwsMailCredentials, "_aws")
    def test_bootstrap_creates_a_separate_gitops_key_without_argument_leaks(
        self, aws
    ) -> None:
        aws.side_effect = [
            subprocess.CompletedProcess([], 0, '{"Account":"123456789012"}'),
            subprocess.CompletedProcess([], 0, ""),
            subprocess.CompletedProcess([], 0, ""),
            subprocess.CompletedProcess([], 0, '{"AccessKeyMetadata":[]}'),
            subprocess.CompletedProcess(
                [],
                0,
                "{\"AccessKey\":{"
                f'\"AccessKeyId\":\"{self.access_id}\",'
                f'\"SecretAccessKey\":\"{self.secret}\"'
                "}}",
            ),
        ]
        bootstrap = {
            BOOTSTRAP_KEYS[0]: self.bootstrap_access_id,
            BOOTSTRAP_KEYS[1]: self.bootstrap_secret,
        }

        self.assertEqual(
            self.credentials._reconcile_gitops_identity(bootstrap),
            {AUTH_KEYS[0]: self.access_id, AUTH_KEYS[1]: self.secret},
        )
        rendered_commands = repr([call.args[0] for call in aws.call_args_list])
        self.assertNotIn(self.bootstrap_access_id, rendered_commands)
        self.assertNotIn(self.bootstrap_secret, rendered_commands)
        self.assertNotIn(self.secret, rendered_commands)


if __name__ == "__main__":
    unittest.main()

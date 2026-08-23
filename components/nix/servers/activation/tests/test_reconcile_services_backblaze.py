from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import MagicMock, patch

import yaml

from reconcile_services_backblaze import (
    BACKUP_CONTRACT_PATH,
    BackblazeClient,
    BackupContract,
    ReconcileError,
    ServicesBackblazeReconciler,
)
from initialize_services_restic import ResticRunner, ServicesResticInitializer
from runtime_contract import CONTRACT_PATH


RUNTIME_FILE = "runtime.sops.yaml"
BACKUPS_FILE = "backups.sops.yaml"


def runtime_document() -> dict:
    return {
        "schemaVersion": 8,
        "secretFile": RUNTIME_FILE,
        "credentials": {"external": ["EXTERNAL_KEY"]},
        "hostCredentials": {
            "host": {"secretFile": "host.sops.yaml", "keys": ["HOST_KEY"]}
        },
        "generatedSecrets": {
            "local": {
                "secretFile": "generated.sops.yaml",
                "keys": [
                    "GENERATED_KEY",
                    "HERMES_BACKUP_RESTIC_PASSWORD",
                    "HOME_ASSISTANT_BACKUP_RESTIC_PASSWORD",
                ],
            }
        },
        "provisionedSecrets": {
            "backblaze-services": {
                "provisioner": "reconcile-services-backblaze",
                "secretFile": RUNTIME_FILE,
                "keys": ["B2_APPLICATION_KEY_ID", "B2_APPLICATION_KEY"],
            },
            "backblaze-hosts": {
                "provisioner": "reconcile-services-backblaze",
                "secretFile": BACKUPS_FILE,
                "keys": [
                    "HERMES_BACKUP_B2_APPLICATION_KEY_ID",
                    "HERMES_BACKUP_B2_APPLICATION_KEY",
                    "HOME_ASSISTANT_BACKUP_B2_APPLICATION_KEY_ID",
                    "HOME_ASSISTANT_BACKUP_B2_APPLICATION_KEY",
                ],
            },
        },
    }


def backup_document() -> dict:
    capabilities = [
        "deleteFiles",
        "listAllBucketNames",
        "listBuckets",
        "listFiles",
        "readBuckets",
        "readFiles",
        "writeFiles",
    ]
    return {
        "provider": "backblaze-b2",
        "bucket": {
            "name": "test-recovery",
            "s3Endpoint": "https://s3.test-region.backblazeb2.com",
            "region": "test-region",
            "operatorBootstrap": {
                "applicationKeyIdFile": "secrets/B2_MASTER_APPLICATION_KEY_ID.key",
                "applicationKeyFile": "secrets/B2_MASTER_APPLICATION_KEY.key",
                "clearAfterSuccess": True,
            },
            "lifecycleRules": [{"fileNamePrefix": "services/"}],
        },
        "services": {
            "kubernetes": {
                "keyName": "test-services-velero",
                "namePrefix": "services/kubernetes/",
                "capabilities": capabilities,
                "secretFile": RUNTIME_FILE,
                "idField": "B2_APPLICATION_KEY_ID",
                "valueField": "B2_APPLICATION_KEY",
            },
            "hosts": [
                {
                    "host": name,
                    "keyName": f"test-services-{name}",
                    "namePrefix": f"services/hosts/{name}/",
                    "secretFile": BACKUPS_FILE,
                    "idField": f"{prefix}_BACKUP_B2_APPLICATION_KEY_ID",
                    "valueField": f"{prefix}_BACKUP_B2_APPLICATION_KEY",
                    "resticPasswordField": f"{prefix}_BACKUP_RESTIC_PASSWORD",
                }
                for name, prefix in (
                    ("hermes", "HERMES"),
                    ("home-assistant", "HOME_ASSISTANT"),
                )
            ],
            "hostCapabilities": capabilities,
        },
    }


class FakeStore:
    def __init__(self) -> None:
        self.values: dict[tuple[Path, str], str] = {}
        self.writes: list[tuple[str, str, str]] = []

    def read(self, secret_file: Path, credential: str) -> str | None:
        return self.values.get((secret_file, credential))

    def write(self, secret_file: Path, values: dict[str, str]) -> None:
        for credential, value in values.items():
            self.values[(secret_file, credential)] = value
        self.writes.append((str(secret_file), *values.values()))


class FakeClient:
    def __init__(self, contract: BackupContract) -> None:
        self.contract = contract
        self.inventory: list[dict] = []
        self.created: list[str] = []
        self.deleted: list[str] = []
        self.policy_updated = False

    def bucket(self, name: str) -> dict:
        assert name == self.contract.bucket_name
        return {
            "bucketId": "bucket-id",
            "bucketType": "allPrivate",
            "defaultServerSideEncryption": {"mode": "SSE-B2"},
            "lifecycleRules": list(self.contract.lifecycle_rules),
        }

    def keys(self) -> list[dict]:
        return list(self.inventory)

    def update_bucket_policy(self, bucket: dict, lifecycle_rules: tuple[dict, ...]) -> bool:
        self.policy_updated = True
        return False

    def create_key(self, bucket_id: str, spec) -> tuple[str, str]:
        assert bucket_id == "bucket-id"
        self.created.append(spec.name)
        return f"id-{len(self.created)}", f"secret-{len(self.created)}"

    def delete_key(self, key_id: str) -> None:
        self.deleted.append(key_id)

class FakeRunner:
    def __init__(self, *, fail: bool = False) -> None:
        self.ready_prefixes: set[str] = set()
        self.initialized: list[str] = []
        self.fail = fail

    def ready(self, spec, key_id: str, application_key: str, password: str) -> bool:
        return spec.prefix in self.ready_prefixes

    def initialize(
        self, spec, key_id: str, application_key: str, password: str
    ) -> None:
        if self.fail:
            raise ReconcileError("safe initialization failure")
        self.initialized.append(spec.prefix)
        self.ready_prefixes.add(spec.prefix)


class ServicesBackblazeReconcilerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        contract_path = self.root / CONTRACT_PATH
        contract_path.parent.mkdir(parents=True)
        contract_path.write_text(
            yaml.safe_dump(
                {"data": {"required-keys.yaml": yaml.safe_dump(runtime_document())}}
            ),
            encoding="utf-8",
        )
        backup_path = self.root / BACKUP_CONTRACT_PATH
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        backup_path.write_text(yaml.safe_dump(backup_document()), encoding="utf-8")
        self.contract = BackupContract.load(self.root)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_contract_routes_three_independent_least_privilege_keys(self) -> None:
        self.assertEqual(len(self.contract.keys), 3)
        self.assertEqual(len({spec.prefix for spec in self.contract.keys}), 3)
        self.assertEqual(
            {spec.secret_file for spec in self.contract.keys},
            {Path(RUNTIME_FILE), Path(BACKUPS_FILE)},
        )
        self.assertTrue(
            all(
                {"listBuckets", "readBuckets"}.issubset(spec.capabilities)
                for spec in self.contract.keys
            )
        )

    def test_apply_creates_and_encrypts_without_reporting_material(self) -> None:
        client = FakeClient(self.contract)
        store = FakeStore()
        reports = ServicesBackblazeReconciler(
            self.contract, client, store
        ).reconcile(apply=True, rotate=False)
        self.assertEqual(client.created, [spec.name for spec in self.contract.keys])
        self.assertEqual(len(store.writes), 3)
        output = "\n".join(reports)
        self.assertNotIn("secret-", output)
        self.assertNotIn("id-", output)

    def test_existing_unrecoverable_key_requires_explicit_rotation(self) -> None:
        client = FakeClient(self.contract)
        client.inventory.append(
            {
                "keyName": self.contract.keys[0].name,
                "applicationKeyId": "existing-id",
            }
        )
        with self.assertRaisesRegex(ReconcileError, "--rotate"):
            ServicesBackblazeReconciler(
                self.contract, client, FakeStore()
            ).reconcile(apply=True, rotate=False)

    def _restic_store(self) -> FakeStore:
        store = FakeStore()
        for spec in self.contract.keys:
            if spec.restic_password_credential is None:
                continue
            store.values[(spec.secret_file, spec.id_credential)] = "scoped-id"
            store.values[(spec.secret_file, spec.key_credential)] = "scoped-secret"
            store.values[
                (spec.restic_password_file, spec.restic_password_credential)
            ] = "restic-password"
        return store

    def test_restic_initializer_uses_scoped_material_and_verifies(self) -> None:
        runner = FakeRunner()
        reports = ServicesResticInitializer(
            self.contract, self._restic_store(), runner
        ).apply()
        self.assertEqual(len(runner.initialized), 2)
        self.assertNotIn("scoped-secret", "\n".join(reports))
        self.assertNotIn("restic-password", "\n".join(reports))

    def test_restic_initializer_reports_safe_failure(self) -> None:
        with self.assertRaisesRegex(ReconcileError, "safe initialization failure"):
            ServicesResticInitializer(
                self.contract, self._restic_store(), FakeRunner(fail=True)
            ).apply()

    def test_restic_verification_does_not_require_an_ambient_home(self) -> None:
        completed = MagicMock(returncode=0)
        with (
            patch(
                "initialize_services_restic.shutil.which",
                return_value="/nix/store/restic/bin/restic",
            ),
            patch(
                "initialize_services_restic.subprocess.run",
                return_value=completed,
            ) as run,
        ):
            runner = ResticRunner(
                self.contract.bucket_name,
                self.contract.s3_endpoint,
                self.contract.region,
            )
            self.assertTrue(
                runner.ready(
                    self.contract.keys[1],
                    "scoped-id",
                    "scoped-secret",
                    "restic-password",
                )
            )
        command = run.call_args.args[0]
        self.assertEqual(
            command[:4],
            [
                "/nix/store/restic/bin/restic",
                "--no-cache",
                "--repo",
                (
                    "s3:https://s3.test-region.backblazeb2.com/test-recovery/"
                    "services/hosts/hermes"
                ),
            ],
        )
        self.assertNotIn("HOME", run.call_args.kwargs["env"])

    def test_native_upload_uses_scoped_protocol_headers(self) -> None:
        client = object.__new__(BackblazeClient)
        client.call = MagicMock(
            return_value={
                "uploadUrl": "https://upload.example.invalid/file",
                "authorizationToken": "upload-token",
            }
        )
        response = MagicMock()
        response.__enter__.return_value = object()
        with (
            patch(
                "reconcile_services_backblaze.urllib.request.urlopen",
                return_value=response,
            ) as urlopen,
            patch(
                "reconcile_services_backblaze.json.load",
                return_value={"fileName": "prefix/config", "fileId": "file-id"},
            ),
        ):
            result = client.upload_file("bucket-id", "prefix/config", b"content")
        self.assertEqual(result, ("prefix/config", "file-id"))
        client.call.assert_called_once_with(
            "b2_get_upload_url", {"bucketId": "bucket-id"}
        )
        request = urlopen.call_args.args[0]
        self.assertEqual(request.data, b"content")
        self.assertEqual(request.get_header("Authorization"), "upload-token")
        self.assertEqual(request.get_header("X-bz-file-name"), "prefix/config")
        self.assertIsNotNone(request.get_header("X-bz-content-sha1"))

    def test_native_upload_classifies_provider_cap_block(self) -> None:
        client = object.__new__(BackblazeClient)
        client.call = MagicMock(
            side_effect=ReconcileError(
                "b2_get_upload_url failed: provider rejected HTTP 403"
            )
        )
        with self.assertRaisesRegex(ReconcileError, "storage cap or account standing"):
            client.upload_file("bucket-id", "prefix/config", b"content")


if __name__ == "__main__":
    unittest.main()

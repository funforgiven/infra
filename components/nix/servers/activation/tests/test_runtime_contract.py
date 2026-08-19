from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import yaml

from runtime_contract import CONTRACT_PATH, ContractError, RuntimeContract


CLUSTER_FILE = Path("cluster-runtime.sops.yaml")
HERMES_FILE = Path("hermes-runtime.sops.yaml")
GENERATED_FILE = Path("generated-runtime.sops.yaml")
PROVISIONED_FILE = Path("provisioned-runtime.sops.yaml")


def contract_document() -> dict:
    return {
        "schemaVersion": 6,
        "secretFile": str(CLUSTER_FILE),
        "credentials": {"initial": ["CLUSTER_KEY"]},
        "hostCredentials": {
            "hermes": {
                "secretFile": str(HERMES_FILE),
                "keys": ["HERMES_TELEGRAM_BOT_TOKEN", "OPENAI_API_KEY"],
            }
        },
        "generatedSecrets": {
            "application": {
                "secretFile": str(GENERATED_FILE),
                "keys": ["GENERATED_KEY"],
            }
        },
        "provisionedSecrets": {
            "provider": {
                "provisioner": "test-provider",
                "secretFile": str(PROVISIONED_FILE),
                "keys": ["PROVISIONED_KEY"],
            }
        },
    }


class RuntimeContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.write_contract(contract_document())

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def write_contract(self, payload: dict) -> None:
        path = self.root / CONTRACT_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        config_map = {"data": {"required-keys.yaml": yaml.safe_dump(payload)}}
        path.write_text(yaml.safe_dump(config_map), encoding="utf-8")

    def write_secret(self, path: Path, keys: list[str]) -> None:
        document = {
            "data": {key: "ENC[test-ciphertext]" for key in keys},
            "sops": {"version": "test"},
        }
        (self.root / path).write_text(yaml.safe_dump(document), encoding="utf-8")

    def test_routes_credentials_to_independent_documents(self) -> None:
        contract = RuntimeContract.load(self.root)
        self.assertEqual(contract.credential("CLUSTER_KEY").secret_file, CLUSTER_FILE)
        self.assertEqual(
            contract.credential("HERMES_TELEGRAM_BOT_TOKEN").secret_file,
            HERMES_FILE,
        )
        self.assertEqual(
            contract.credential("OPENAI_API_KEY").secret_file,
            HERMES_FILE,
        )
        self.assertEqual(
            contract.credential("OPENAI_API_KEY").consumer,
            "hermes",
        )
        self.assertEqual(
            contract.generated_credential("GENERATED_KEY").secret_file,
            GENERATED_FILE,
        )
        self.assertTrue(contract.managed_credential("GENERATED_KEY").generated)
        provisioned = contract.provisioned_credential("PROVISIONED_KEY")
        self.assertEqual(provisioned.secret_file, PROVISIONED_FILE)
        self.assertTrue(provisioned.provisioned)
        self.assertEqual(provisioned.provisioner, "test-provider")

    def test_derived_keys_are_not_externally_enrollable(self) -> None:
        contract = RuntimeContract.load(self.root)
        with self.assertRaisesRegex(ContractError, "unknown services credential"):
            contract.credential("GENERATED_KEY")
        with self.assertRaisesRegex(ContractError, "unknown services credential"):
            contract.credential("PROVISIONED_KEY")

    def test_rejects_duplicate_keys(self) -> None:
        payload = contract_document()
        payload["hostCredentials"]["hermes"]["keys"] = ["CLUSTER_KEY"]
        self.write_contract(payload)
        with self.assertRaisesRegex(ContractError, "duplicate credential"):
            RuntimeContract.load(self.root)

    def test_requires_every_key_as_ciphertext(self) -> None:
        contract = RuntimeContract.load(self.root)
        self.write_secret(
            CLUSTER_FILE,
            ["CLUSTER_KEY"],
        )
        self.write_secret(HERMES_FILE, [])
        self.write_secret(GENERATED_FILE, ["GENERATED_KEY"])
        self.write_secret(PROVISIONED_FILE, ["PROVISIONED_KEY"])
        with self.assertRaisesRegex(ContractError, "OPENAI_API_KEY"):
            contract.verify_ciphertext()
        self.write_secret(
            HERMES_FILE,
            ["HERMES_TELEGRAM_BOT_TOKEN", "OPENAI_API_KEY"],
        )
        contract.verify_ciphertext()

    def test_can_defer_one_provider_without_weakening_other_checks(self) -> None:
        contract = RuntimeContract.load(self.root)
        self.write_secret(CLUSTER_FILE, ["CLUSTER_KEY"])
        self.write_secret(
            HERMES_FILE,
            ["HERMES_TELEGRAM_BOT_TOKEN", "OPENAI_API_KEY"],
        )
        self.write_secret(GENERATED_FILE, ["GENERATED_KEY"])
        self.write_secret(PROVISIONED_FILE, [])
        contract.verify_ciphertext(frozenset({"test-provider"}))
        with self.assertRaisesRegex(ContractError, "PROVISIONED_KEY"):
            contract.verify_ciphertext()

    def test_rejects_unknown_deferred_provider(self) -> None:
        contract = RuntimeContract.load(self.root)
        with self.assertRaisesRegex(ContractError, "unknown provisioners"):
            contract.verify_ciphertext(frozenset({"typo-provider"}))

    def test_rejects_paths_outside_repository(self) -> None:
        payload = contract_document()
        payload["hostCredentials"]["hermes"]["secretFile"] = "../secret.yaml"
        self.write_contract(payload)
        with self.assertRaisesRegex(ContractError, "inside the repository"):
            RuntimeContract.load(self.root)

    def test_provisioned_secrets_require_a_provisioner(self) -> None:
        payload = contract_document()
        del payload["provisionedSecrets"]["provider"]["provisioner"]
        self.write_contract(payload)
        with self.assertRaisesRegex(ContractError, "provisioner"):
            RuntimeContract.load(self.root)


if __name__ == "__main__":
    unittest.main()

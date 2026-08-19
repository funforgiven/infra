from pathlib import Path
import unittest

from reconcile_services_openai import (
    OpenAIKeyReconciler,
    OpenAIKeySpec,
    OpenAIReconcileError,
)


SPEC = OpenAIKeySpec(
    project_name="fahrican-hermes-production",
    service_account_name="fahrican-hermes-production-service-account",
    key_name="fahrican-hermes-production-runtime",
    scopes=("api.responses.write",),
    administration_file=Path("openai-admin.sops.yaml"),
    administration_credential="OPENAI_ADMIN_KEY",
    output_file=Path("hermes.sops.yaml"),
    output_credential="OPENAI_API_KEY",
)


class FakeStore:
    def __init__(self) -> None:
        self.value = None

    def read(self, secret_file: Path, credential: str) -> str | None:
        return self.value

    def write(self, secret_file: Path, values: dict[str, str]) -> None:
        self.value = values[SPEC.output_credential]


class FakeClient:
    def __init__(self) -> None:
        self.inventory = []
        self.created = None

    def project(self, name: str) -> dict:
        return {"id": "project-id", "name": name, "status": "active"}

    def service_account(self, project_id: str, name: str) -> dict:
        return {"id": "account-id", "name": name, "role": "none"}

    def keys(self, project_id: str) -> list[dict]:
        return list(self.inventory)

    def create(
        self, project_id: str, service_account_id: str, spec: OpenAIKeySpec
    ) -> str:
        self.created = (project_id, service_account_id, spec.key_name, spec.scopes)
        return "sk-new-service-account-secret"


def remote_key() -> dict:
    return {
        "id": "key-id",
        "name": SPEC.key_name,
        "owner": {
            "type": "service_account",
            "service_account": {"id": "account-id"},
        },
    }


class OpenAIKeyReconcilerTest(unittest.TestCase):
    def test_creates_scoped_key_without_reporting_material(self) -> None:
        client = FakeClient()
        store = FakeStore()
        report = OpenAIKeyReconciler(SPEC, client, store).reconcile(apply=True)
        self.assertEqual(
            client.created,
            (
                "project-id",
                "account-id",
                SPEC.key_name,
                ("api.responses.write",),
            ),
        )
        self.assertEqual(store.value, "sk-new-service-account-secret")
        self.assertNotIn("sk-new", report)
        self.assertNotIn("key-id", report)

    def test_current_key_requires_remote_metadata_and_ciphertext(self) -> None:
        client = FakeClient()
        client.inventory = [remote_key()]
        store = FakeStore()
        store.value = "sk-existing-service-account-secret"
        self.assertEqual(
            OpenAIKeyReconciler(SPEC, client, store).reconcile(apply=False),
            f"{SPEC.key_name}: current",
        )

    def test_partial_state_requires_declarative_account_replacement(self) -> None:
        client = FakeClient()
        client.inventory = [remote_key()]
        with self.assertRaisesRegex(OpenAIReconcileError, "replace the service account"):
            OpenAIKeyReconciler(SPEC, client, FakeStore()).reconcile(apply=True)

    def test_ignores_keys_owned_by_other_service_accounts(self) -> None:
        client = FakeClient()
        key = remote_key()
        key["owner"]["service_account"]["id"] = "different-account"
        client.inventory = [key]
        store = FakeStore()
        OpenAIKeyReconciler(SPEC, client, store).reconcile(apply=True)
        self.assertIsNotNone(client.created)


if __name__ == "__main__":
    unittest.main()

from pathlib import Path
import unittest

from reconcile_services_openai import (
    OpenAIAdminRetirer,
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
    administration_key_name="fahrican-infra-openai-control-plane",
    output_file=Path("hermes.sops.yaml"),
    output_credential="OPENAI_API_KEY",
    model_ids=("gpt-5.6-luna",),
    hosted_tools=(
        "code_interpreter",
        "file_search",
        "image_generation",
        "mcp",
        "web_search",
    ),
    hard_limit_amount=5000,
    hard_limit_currency="USD",
    hard_limit_interval="month",
)


class FakeStore:
    def __init__(self) -> None:
        self.value = None
        self.administration_value = "admin-secret"

    def read(self, secret_file: Path, credential: str) -> str | None:
        if credential == SPEC.administration_credential:
            return self.administration_value
        return self.value

    def write(self, secret_file: Path, values: dict[str, str]) -> None:
        self.value = values[SPEC.output_credential]

    def remove(self, secret_file: Path, credential: str) -> None:
        if credential == SPEC.administration_credential:
            self.administration_value = None


class FakeClient:
    def __init__(self) -> None:
        self.inventory = []
        self.created = None
        self.deleted_administration_key = None

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

    def model_permissions(self, project_id: str) -> dict:
        return {"mode": "allow_list", "model_ids": list(SPEC.model_ids)}

    def hosted_tool_permissions(self, project_id: str) -> dict:
        return {tool: False for tool in SPEC.hosted_tools}

    def hard_spend_limit(self, project_id: str) -> dict:
        return {
            "threshold_amount": SPEC.hard_limit_amount,
            "currency": SPEC.hard_limit_currency,
            "interval": SPEC.hard_limit_interval,
        }

    def administration_keys(self) -> list[dict]:
        return [{"id": "admin-key-id", "name": SPEC.administration_key_name}]

    def delete_administration_key(self, key_id: str) -> None:
        self.deleted_administration_key = key_id


def remote_key() -> dict:
    return {
        "id": "key-id",
        "name": SPEC.key_name,
        "scopes": list(SPEC.scopes),
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


class OpenAIAdminRetirerTest(unittest.TestCase):
    def current_boundary(self) -> tuple[FakeClient, FakeStore]:
        client = FakeClient()
        client.inventory = [remote_key()]
        store = FakeStore()
        store.value = "sk-existing-service-account-secret"
        return client, store

    def test_revokes_only_after_runtime_boundary_and_policy_verification(self) -> None:
        client, store = self.current_boundary()
        report = OpenAIAdminRetirer(SPEC, client, store).retire()
        self.assertEqual(client.deleted_administration_key, "admin-key-id")
        self.assertIsNone(store.administration_value)
        self.assertNotIn("admin-secret", report)
        self.assertNotIn("sk-existing", report)

    def test_refuses_retirement_without_stored_runtime_key(self) -> None:
        client, store = self.current_boundary()
        store.value = None
        with self.assertRaisesRegex(OpenAIReconcileError, "runtime key"):
            OpenAIAdminRetirer(SPEC, client, store).retire()
        self.assertIsNone(client.deleted_administration_key)

    def test_refuses_retirement_when_runtime_scope_drifted(self) -> None:
        client, store = self.current_boundary()
        client.inventory[0]["scopes"] = ["api.responses.write", "api.files.write"]
        with self.assertRaisesRegex(OpenAIReconcileError, "scope metadata"):
            OpenAIAdminRetirer(SPEC, client, store).retire()
        self.assertIsNone(client.deleted_administration_key)

    def test_refuses_retirement_when_hard_limit_drifted(self) -> None:
        client, store = self.current_boundary()
        client.hard_spend_limit = lambda project_id: {
            "threshold_amount": 1000,
            "currency": "USD",
            "interval": "month",
        }
        with self.assertRaisesRegex(OpenAIReconcileError, "hard spend limit"):
            OpenAIAdminRetirer(SPEC, client, store).retire()
        self.assertIsNone(client.deleted_administration_key)

    def test_refuses_retirement_when_hosted_tool_is_enabled(self) -> None:
        client, store = self.current_boundary()
        client.hosted_tool_permissions = lambda project_id: {
            **{tool: False for tool in SPEC.hosted_tools},
            "file_search": True,
        }
        with self.assertRaisesRegex(OpenAIReconcileError, "hosted-tool"):
            OpenAIAdminRetirer(SPEC, client, store).retire()
        self.assertIsNone(client.deleted_administration_key)


if __name__ == "__main__":
    unittest.main()

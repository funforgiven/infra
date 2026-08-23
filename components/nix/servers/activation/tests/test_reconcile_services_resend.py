from pathlib import Path
import unittest

from reconcile_services_resend import (
    ResendKeyReconciler,
    ResendKeySpec,
    ResendReconcileError,
)


SPEC = ResendKeySpec(
    name="fahrican-stalwart-smtp",
    permission="sending_access",
    domain="fahrican.com",
    administration_file=Path("runtime.sops.yaml"),
    administration_credential="RESEND_ADMIN_API_KEY",
    output_file=Path("resend.sops.yaml"),
    output_credential="STALWART_RESEND_API_KEY",
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
        self.deleted = []

    def domain(self, name: str) -> dict:
        return {"id": "domain-id", "name": name, "status": "verified"}

    def keys(self) -> list[dict]:
        return list(self.inventory)

    def create(self, spec: ResendKeySpec, domain_id: str) -> tuple[str, str]:
        self.created = (spec.name, spec.permission, domain_id)
        return "new-id", "new-secret"

    def delete(self, key_id: str) -> None:
        self.deleted.append(key_id)


class ResendKeyReconcilerTest(unittest.TestCase):
    def test_creates_domain_scoped_key_without_reporting_material(self) -> None:
        client = FakeClient()
        store = FakeStore()
        report = ResendKeyReconciler(SPEC, client, store).reconcile(
            apply=True, rotate=False
        )
        self.assertEqual(
            client.created,
            ("fahrican-stalwart-smtp", "sending_access", "domain-id"),
        )
        self.assertEqual(store.value, "new-secret")
        self.assertNotIn("new-secret", report)
        self.assertNotIn("new-id", report)

    def test_partial_or_unrecoverable_state_requires_rotation(self) -> None:
        client = FakeClient()
        client.inventory = [{"id": "old-id", "name": SPEC.name}]
        with self.assertRaisesRegex(ResendReconcileError, "--rotate"):
            ResendKeyReconciler(SPEC, client, FakeStore()).reconcile(
                apply=True, rotate=False
            )

    def test_rotation_switches_ciphertext_before_revoking_old_key(self) -> None:
        client = FakeClient()
        client.inventory = [{"id": "old-id", "name": SPEC.name}]
        store = FakeStore()
        store.value = "old-secret"
        ResendKeyReconciler(SPEC, client, store).reconcile(apply=True, rotate=True)
        self.assertEqual(store.value, "new-secret")
        self.assertEqual(client.deleted, ["old-id"])


if __name__ == "__main__":
    unittest.main()

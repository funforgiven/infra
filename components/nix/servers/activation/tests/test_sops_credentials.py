from pathlib import Path
import unittest

from sops_credentials import SopsCredentialError, SopsCredentialStore


SECRET_FILE = Path("runtime.sops.yaml")


class MemoryCredentialStore(SopsCredentialStore):
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.fail_value: str | None = None
        self.corrupt_value: str | None = None
        self.syncs = 0

    def _path(self, relative_path: Path) -> Path:
        return relative_path

    def read(self, secret_file: Path, credential: str) -> str | None:
        return self.values.get(credential)

    def _set(self, path: Path, credential: str, value: str) -> None:
        if value == self.fail_value:
            raise SopsCredentialError("simulated SOPS set failure")
        self.values[credential] = (
            "corrupt-value" if value == self.corrupt_value else value
        )

    def _unset(self, path: Path, credential: str) -> None:
        self.values.pop(credential, None)

    def _sync(self, path: Path) -> None:
        self.syncs += 1


class SopsCredentialStoreTest(unittest.TestCase):
    def test_partial_initial_write_removes_new_values(self) -> None:
        store = MemoryCredentialStore()
        store.fail_value = "new-secret"

        with self.assertRaisesRegex(SopsCredentialError, "simulated SOPS set failure"):
            store.write(
                SECRET_FILE,
                {"KEY_ID": "new-id", "KEY": "new-secret"},
            )

        self.assertEqual(store.values, {})
        self.assertEqual(store.syncs, 1)

    def test_partial_write_failure_restores_previous_values(self) -> None:
        store = MemoryCredentialStore()
        store.values = {"KEY_ID": "old-id", "KEY": "old-secret"}
        store.fail_value = "new-secret"

        with self.assertRaisesRegex(SopsCredentialError, "simulated SOPS set failure"):
            store.write(
                SECRET_FILE,
                {"KEY_ID": "new-id", "KEY": "new-secret"},
            )

        self.assertEqual(store.values, {"KEY_ID": "old-id", "KEY": "old-secret"})
        self.assertEqual(store.syncs, 1)

    def test_verification_failure_restores_previous_values(self) -> None:
        store = MemoryCredentialStore()
        store.values = {"KEY_ID": "old-id", "KEY": "old-secret"}
        store.corrupt_value = "new-secret"

        with self.assertRaisesRegex(SopsCredentialError, "cannot verify encrypted KEY"):
            store.write(
                SECRET_FILE,
                {"KEY_ID": "new-id", "KEY": "new-secret"},
            )

        self.assertEqual(store.values, {"KEY_ID": "old-id", "KEY": "old-secret"})
        self.assertEqual(store.syncs, 2)


if __name__ == "__main__":
    unittest.main()

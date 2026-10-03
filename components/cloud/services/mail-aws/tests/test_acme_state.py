import base64
import importlib.util
from pathlib import Path
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location("acme_state", Path(__file__).parents[1] / "acme-state.py")
state = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(state)


class AcmeStateTest(unittest.TestCase):
    def test_restore_preserves_binary_state_and_can_retry_after_interruption(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            document = {".lego/accounts/test/key": base64.b64encode(b"test\x00key").decode()}
            state.restore(document, root)
            state.restore(document, root)
            path = root / ".lego/accounts/test/key"
            self.assertEqual(path.read_bytes(), b"test\x00key")
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_restore_rejects_escaping_paths_before_writing_any_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("../outside", "/outside", "nested/../../outside", "."):
                with self.subTest(name=name), self.assertRaises(ValueError):
                    state.restore({"valid": "dGVzdA==", name: "dGVzdA=="}, root)
                self.assertFalse((root / "valid").exists())

    def test_restore_does_not_follow_symlink_outside_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "acme"
            root.mkdir()
            (root / "escape").symlink_to(root.parent, target_is_directory=True)
            with self.assertRaises(ValueError):
                state.restore({"escape/key": "dGVzdA=="}, root)
            self.assertFalse((root.parent / "key").exists())

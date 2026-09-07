import importlib.util
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest import mock


SOURCE = Path(__file__).resolve().parents[5] / "deployments/homelab/cloud/services/46-forge/render-forgejo.py"
SPEC = importlib.util.spec_from_file_location("forgejo_render", SOURCE)
RENDER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RENDER)


class SigningKeyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.secrets = self.root / "secrets"
        self.secrets.mkdir()
        self.directory = self.root / "data/.ssh"
        self.material = {"private-key": b"private fixture\n", "public-key": b"public fixture\n"}
        for name, data in self.material.items():
            (self.secrets / name).write_bytes(data)

    def install(self):
        RENDER.install_signing_key(self.directory, self.secrets)

    def test_restart_preserves_key_and_restricts_permissions(self):
        self.install()
        private = self.directory / "instance-signing"
        public = self.directory / "instance-signing.pub"
        inode = private.stat().st_ino
        private.chmod(0o644)
        self.install()
        self.assertEqual(private.stat().st_ino, inode)
        self.assertEqual(private.read_bytes(), self.material["private-key"])
        self.assertEqual(public.read_bytes(), self.material["public-key"])
        self.assertEqual(stat.S_IMODE(self.directory.stat().st_mode), 0o700)
        for path in (private, public):
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_changed_pair_is_rejected_before_any_key_is_written(self):
        self.directory.mkdir(parents=True)
        public = self.directory / "instance-signing.pub"
        public.write_bytes(b"different public fixture\n")
        with self.assertRaisesRegex(ValueError, "key changed"):
            self.install()
        self.assertFalse((self.directory / "instance-signing").exists())
        self.assertEqual(public.read_bytes(), b"different public fixture\n")

    def test_interrupted_publication_leaves_no_partial_key_and_can_retry(self):
        with mock.patch.object(RENDER.os, "link", side_effect=OSError("interrupted")):
            with self.assertRaises(OSError):
                self.install()
        self.assertEqual(list(self.directory.iterdir()), [])
        self.install()
        self.assertEqual((self.directory / "instance-signing").read_bytes(), self.material["private-key"])

    def test_linked_parent_and_nonregular_key_are_rejected(self):
        elsewhere = self.root / "elsewhere"
        elsewhere.mkdir()
        self.directory.parent.mkdir()
        self.directory.symlink_to(elsewhere, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "signing directory"):
            self.install()
        self.assertEqual(list(elsewhere.iterdir()), [])
        self.directory.unlink()
        self.directory.mkdir()
        os.mkfifo(self.directory / "instance-signing")
        with self.assertRaisesRegex(ValueError, "regular file"):
            self.install()
        self.assertFalse((self.directory / "instance-signing.pub").exists())


if __name__ == "__main__":
    unittest.main()

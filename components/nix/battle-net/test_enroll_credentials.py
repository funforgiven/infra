import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import enroll_credentials as credentials


class EnrollmentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.identity_directory = tempfile.TemporaryDirectory()
        cls.identity = Path(cls.identity_directory.name) / "age-key.txt"
        subprocess.run(["age-keygen", "-o", str(cls.identity)], capture_output=True, check=True)
        cls.recipient = subprocess.check_output(
            ["age-keygen", "-y", str(cls.identity)], text=True
        ).strip()
        cls.environment = patch.dict(os.environ, {"SOPS_AGE_KEY_FILE": str(cls.identity)})
        cls.environment.start()

    @classmethod
    def tearDownClass(cls):
        cls.environment.stop()
        cls.identity_directory.cleanup()

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / ".sops.yaml").write_text(
            "creation_rules:\n  - path_regex: '^secrets/instawow\\.json$'\n"
            f"    age: {self.recipient}\n"
        )
        (self.root / "secrets").mkdir()
        self.secret = self.root / credentials.SECRET_FILE
        self.secret.write_text(credentials.sops(
            "encrypt", "--input-type", "binary", "--output-type", "binary",
            "--filename-override", str(credentials.SECRET_FILE), "/dev/stdin",
            input=json.dumps({"cfcore": None, "github": None}), cwd=self.root,
        ))
        self.intake = self.root / "secrets/INSTAWOW_CURSEFORGE_API_KEY.key"
        self.intake.write_text("test-curseforge-credential\n")
        self.intake.chmod(0o600)

    def document(self):
        return json.loads(credentials.sops("decrypt", "--output-type", "binary", str(self.secret)))

    def test_success_encrypts_verifies_and_clears_intake(self):
        credentials.enroll_from_file(self.root, "curseforge", self.root / "secrets")
        self.assertEqual(self.document(), {"cfcore": "test-curseforge-credential", "github": None})
        self.assertEqual(self.intake.read_bytes(), b"")
        self.assertNotIn("test-curseforge-credential", self.secret.read_text())
        self.assertFalse(list(self.secret.parent.glob(".instawow-*.json")))

    def test_rotation_preserves_other_providers(self):
        credentials.enroll(self.root, "github", "test-github-credential")
        credentials.enroll_from_file(self.root, "curseforge", self.root / "secrets")
        self.assertEqual(self.document(), {
            "cfcore": "test-curseforge-credential", "github": "test-github-credential",
        })

    def test_failure_keeps_ciphertext_and_intake(self):
        ciphertext = self.secret.read_bytes()
        with patch.object(credentials, "sops", side_effect=RuntimeError("simulated SOPS failure")):
            with self.assertRaises(RuntimeError):
                credentials.enroll_from_file(self.root, "curseforge", self.root / "secrets")
        self.assertEqual(self.secret.read_bytes(), ciphertext)
        self.assertEqual(self.intake.read_text(), "test-curseforge-credential\n")

    def test_round_trip_failure_keeps_original_ciphertext_and_intake(self):
        ciphertext = self.secret.read_bytes()
        real_sops = credentials.sops

        def corrupt_verification(*arguments, **kwargs):
            if arguments[0] == "decrypt" and Path(arguments[-1]).name.startswith(".instawow-"):
                return '{}'
            return real_sops(*arguments, **kwargs)

        with patch.object(credentials, "sops", side_effect=corrupt_verification):
            with self.assertRaisesRegex(RuntimeError, "round-trip verification"):
                credentials.enroll_from_file(self.root, "curseforge", self.root / "secrets")
        self.assertEqual(self.secret.read_bytes(), ciphertext)
        self.assertEqual(self.intake.read_text(), "test-curseforge-credential\n")
        self.assertFalse(list(self.secret.parent.glob(".instawow-*.json")))

    def test_empty_or_multiline_input_is_rejected(self):
        for value in ["", "\n", "first\nsecond", "first\rsecond"]:
            self.intake.write_text(value)
            with self.assertRaises(ValueError):
                credentials.enroll_from_file(self.root, "curseforge", self.root / "secrets")
            self.assertEqual(self.intake.read_bytes(), value.encode())

    def test_intake_must_have_private_permissions(self):
        self.intake.chmod(0o644)
        with self.assertRaisesRegex(ValueError, "mode 0600"):
            credentials.enroll_from_file(self.root, "curseforge", self.root / "secrets")

    def test_symlink_intake_is_rejected(self):
        target = self.intake.with_suffix(".original")
        self.intake.rename(target)
        self.intake.symlink_to(target)
        with self.assertRaises(OSError):
            credentials.enroll_from_file(self.root, "curseforge", self.root / "secrets")
        self.assertEqual(target.read_text(), "test-curseforge-credential\n")


if __name__ == "__main__":
    unittest.main()

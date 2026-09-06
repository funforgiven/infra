"""Recovery must reject corruption and never publish an incomplete image set."""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

SCRIPT = Path(__file__).resolve().parents[5] / 'deployments/homelab/cloud/services/46-forge/native_backup.py'
spec = importlib.util.spec_from_file_location('native_backup', SCRIPT)
backup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backup)


class NativeRecovery(unittest.TestCase):
    def fixture(self, platform):
        files = {name: (platform + '/' + name).encode() for name in backup.FILES[platform]}
        manifest = {'platform': platform, 'source_revision': 'a' * 40, 'qualification_runs': [1, 2],
                    'created_at': int(time.time()) - 60, 'qualified_at': int(time.time()),
                    'files': {name: {'sha256': hashlib.sha256(value).hexdigest(), 'size': len(value)}
                              for name, value in files.items()}}
        return manifest, backup.encoded(manifest) + b''.join(files[name] for name in sorted(files))

    def receive(self, root, payload):
        return subprocess.run([sys.executable, str(SCRIPT), '--receive', '--root', str(root)],
                              input=payload, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def test_restore_requires_both_platforms_and_detects_corruption(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(self.receive(root, self.fixture('windows')[1]).returncode, 0)
            with self.assertRaisesRegex(RuntimeError, 'Both qualified'):
                backup.verify_index(root)
            self.assertEqual(self.receive(root, self.fixture('macos')[1]).returncode, 0)
            index = backup.verify_index(root)
            image = root / 'native/macos' / index['platforms']['macos']['manifest_sha256'] / 'disk.qcow2'
            image.write_bytes(b'X' * image.stat().st_size)
            with self.assertRaisesRegex(RuntimeError, 'checksum mismatch'):
                backup.verify_index(root)

    def test_interrupted_publication_keeps_prior_completed_version(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(self.receive(root, self.fixture('windows')[1]).returncode, 0)
            previous = (root / 'native-index.json').read_bytes()
            manifest, payload = self.fixture('macos')
            result = self.receive(root, payload[:-1])
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual((root / 'native-index.json').read_bytes(), previous)
            self.assertEqual(list((root / 'native/macos').iterdir()), [])

    def test_manifest_cannot_name_arbitrary_files_or_skip_fresh_guest_proof(self):
        manifest, _ = self.fixture('macos')
        manifest['files']['../../runtime.sops.yaml'] = manifest['files'].pop('disk.qcow2')
        with self.assertRaisesRegex(ValueError, 'Unexpected native backup files'):
            backup.validate(manifest)
        manifest, _ = self.fixture('windows')
        manifest['qualification_runs'] = [1, 1]
        with self.assertRaisesRegex(ValueError, 'Two distinct'):
            backup.validate(manifest)


if __name__ == '__main__':
    unittest.main()

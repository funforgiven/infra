import hashlib
import importlib.util
import io
from pathlib import Path
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[5]
SOURCE = ROOT / 'deployments/homelab/cloud/services/25-home-automation'
spec = importlib.util.spec_from_file_location('thread_recovery', SOURCE / 'thread-recovery.py')
recovery = importlib.util.module_from_spec(spec)
spec.loader.exec_module(recovery)


def tar_bytes(files, symlink=False):
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode='w:gz') as archive:
        for name, payload in files.items():
            member = tarfile.TarInfo(name)
            if symlink:
                member.type, member.linkname = tarfile.SYMTYPE, '/etc/passwd'
            else:
                member.size = len(payload)
            archive.addfile(member, io.BytesIO(payload))
    return stream.getvalue()


def dataset():
    fields = {0: b'\x00\x00\x19', 1: b'\x12\x34', 2: b'pan-test', 3: b'Test',
              4: bytes(16), 5: bytes(16), 7: bytes(8), 12: bytes(4), 14: bytes(8)}
    return b''.join(bytes([kind, len(value)]) + value for kind, value in fields.items()).hex().encode()


class ThreadRecoveryTests(unittest.TestCase):
    def archive(self, directory, dataset_bytes=None, state=None, corrupt=False):
        files = {'thread.tar.gz': state or tar_bytes({'thread/0_test.data': b'native settings'}),
                 'dataset.txt': dataset_bytes if dataset_bytes is not None else dataset(),
                 'created-at': b'1789506000\n'}
        files['SHA256SUMS'] = ''.join(f'{hashlib.sha256(value).hexdigest()}  {name}\n'
                                    for name, value in files.items()).encode()
        if corrupt:
            files['thread.tar.gz'] = tar_bytes({'thread/0_test.data': b'changed settings'})
        path = Path(directory) / 'thread-recovery.tar.gz'
        path.write_bytes(tar_bytes(files))
        return path

    def test_native_state_dataset_and_checksums_are_verified_without_extraction(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(1789506000, recovery.verify(self.archive(directory)))
            self.assertEqual(['thread-recovery.tar.gz'], [p.name for p in Path(directory).iterdir()])

    def test_corruption_and_truncated_datasets_fail_even_with_recomputed_checksums(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                recovery.verify(self.archive(directory, corrupt=True))
            for data in (b'not-hex', dataset()[:-2], b'001000'):
                with self.subTest(dataset=data), self.assertRaises(ValueError):
                    recovery.verify(self.archive(directory, dataset_bytes=data))

    def test_symlinks_traversal_and_missing_native_settings_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            for state in (tar_bytes({'thread/0_test.data': b''}, symlink=True),
                          tar_bytes({'thread/../escape.data': b'escape'}),
                          tar_bytes({'thread/empty': b''})):
                with self.assertRaises(ValueError):
                    recovery.verify(self.archive(directory, state=state))


if __name__ == '__main__':
    unittest.main()

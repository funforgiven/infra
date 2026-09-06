"""The macOS host waits for cleanup ownership without disturbing its predecessor."""
import fcntl
import importlib.util
import io
import os
from pathlib import Path
import selectors
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / 'macos' / 'host-job.py'
spec = importlib.util.spec_from_file_location('macos_host_lock', SCRIPT)
host = importlib.util.module_from_spec(spec)
spec.loader.exec_module(host)


class MacOSHostLock(unittest.TestCase):
    def test_uncontended_lock_retains_exclusive_ownership(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, 'job.lock')
            with path.open('w') as owner, path.open('w') as contender, \
                    patch('sys.stdout', new_callable=io.StringIO):
                host.acquire_job_lock(owner, timeout=0.2, interval=0.01)
                with self.assertRaises(BlockingIOError):
                    fcntl.flock(contender, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def test_real_competing_process_waits_until_owner_releases_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, 'job.lock')
            acquired = Path(directory, 'acquired')
            code = (
                'import importlib.util\n'
                f'spec=importlib.util.spec_from_file_location("host", {str(SCRIPT)!r})\n'
                'host=importlib.util.module_from_spec(spec); spec.loader.exec_module(host)\n'
                f'with open({str(path)!r}, "w") as lock:\n'
                ' host.acquire_job_lock(lock, timeout=2, interval=0.02)\n'
                f' host.Path({str(acquired)!r}).write_text("owned")\n'
            )
            with path.open('w') as owner:
                fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
                child = subprocess.Popen([sys.executable, '-u', '-c', code],
                                         stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                try:
                    observed = b''
                    deadline = time.monotonic() + 3
                    with selectors.DefaultSelector() as selector:
                        selector.register(child.stdout, selectors.EVENT_READ)
                        while b'Waiting for previous macOS job cleanup' not in observed:
                            self.assertLess(time.monotonic(), deadline)
                            if selector.select(timeout=0.1):
                                chunk = os.read(child.stdout.fileno(), 4096)
                                self.assertTrue(chunk, 'contender exited before waiting')
                                observed += chunk
                    self.assertIsNone(child.poll())
                    self.assertFalse(acquired.exists())
                    fcntl.flock(owner, fcntl.LOCK_UN)
                    output, errors = child.communicate(timeout=3)
                    self.assertEqual(child.returncode, 0, errors.decode())
                    self.assertEqual(acquired.read_text(), 'owned')
                    self.assertIn(b'broker channel checked', observed + output)
                finally:
                    if child.poll() is None:
                        child.kill()
                    child.communicate(timeout=3)

    def test_timeout_preserves_preceding_owner_and_bounds_wait(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, 'job.lock')
            with path.open('w') as owner, path.open('w') as contender, \
                    path.open('w') as probe, patch('sys.stdout', new_callable=io.StringIO) as output:
                fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
                started = time.monotonic()
                with self.assertRaisesRegex(RuntimeError, 'deadline'):
                    host.acquire_job_lock(contender, timeout=0.1, interval=0.02)
                self.assertLess(time.monotonic() - started, 1)
                self.assertIn('Waiting for previous macOS job cleanup', output.getvalue())
                with self.assertRaises(BlockingIOError):
                    fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
                fcntl.flock(owner, fcntl.LOCK_UN)
                fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def test_closed_output_prevents_even_uncontended_acquisition(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, 'job.lock')
            reader, writer = os.pipe()
            os.close(reader)
            # Write-through to a real readerless pipe, with no buffered bytes
            # left to raise a second exception while closing the test stream.
            with io.TextIOWrapper(os.fdopen(writer, 'wb', buffering=0), write_through=True) as output, \
                    path.open('w') as contender, path.open('w') as probe, \
                    patch('sys.stdout', output):
                with self.assertRaises(BrokenPipeError):
                    host.acquire_job_lock(contender, timeout=0.2, interval=0.01)
                fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def test_disconnect_while_waiting_aborts_before_released_lock_is_acquired(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, 'job.lock')
            reader, writer = os.pipe()
            with io.TextIOWrapper(os.fdopen(writer, 'wb', buffering=0), write_through=True) as output, \
                    path.open('w') as owner, path.open('w') as contender, path.open('w') as probe:
                fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
                disconnected = False

                def disconnect_and_release(_duration):
                    nonlocal disconnected
                    os.close(reader)
                    disconnected = True
                    fcntl.flock(owner, fcntl.LOCK_UN)

                try:
                    with patch('sys.stdout', output), patch.object(host.time, 'sleep', side_effect=disconnect_and_release):
                        with self.assertRaises(BrokenPipeError):
                            host.acquire_job_lock(contender, timeout=0.2, interval=0.01)
                    self.assertTrue(disconnected)
                    fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
                finally:
                    if not disconnected:
                        os.close(reader)

    def test_invalid_limits_fail_before_flock_or_output(self):
        for timeout, interval in ((0, 1), (181, 1), (float('inf'), 1),
                                  (float('nan'), 1), (1, 0), (1, 11)):
            with self.subTest(timeout=timeout, interval=interval), \
                    patch.object(host.fcntl, 'flock') as flock, patch('builtins.print') as output:
                with self.assertRaises(ValueError):
                    host.acquire_job_lock(None, timeout=timeout, interval=interval)
                flock.assert_not_called()
                output.assert_not_called()

    def test_non_contention_errors_are_not_retried(self):
        with patch.object(host.fcntl, 'flock', side_effect=PermissionError('fixture')), \
                patch.object(host.time, 'sleep') as sleep, patch('sys.stdout', new_callable=io.StringIO):
            with self.assertRaises(PermissionError):
                host.acquire_job_lock(None, timeout=0.2, interval=0.01)
            sleep.assert_not_called()


if __name__ == '__main__':
    unittest.main()

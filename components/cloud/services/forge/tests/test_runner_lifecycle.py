"""Bound revoked/cancelled runner cleanup without treating outages as revocation."""
import importlib.util
import io
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys
import tempfile
import time
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / 'run-one-job.py'
spec = importlib.util.spec_from_file_location('one_job', SCRIPT)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class RunnerLifecycle(unittest.TestCase):
    def run_child(self, code):
        output = io.BytesIO()
        started = time.monotonic()
        result = runner.supervise([sys.executable, '-u', '-c', code], output, grace=0.1)
        self.assertLess(time.monotonic() - started, 3)
        return result, output.getvalue()

    def test_output_and_ordinary_exit_are_preserved(self):
        result, output = self.run_child(
            'import sys; print("stdout"); print("stderr", file=sys.stderr); sys.exit(7)')
        self.assertEqual(result, 7)
        self.assertEqual(output, b'stdout\nstderr\n')

    def test_original_signal_handlers_are_restored(self):
        before = {number: signal.getsignal(number) for number in (signal.SIGTERM, signal.SIGINT)}
        self.run_child('pass')
        self.assertEqual(before, {number: signal.getsignal(number) for number in before})

    def test_transient_errors_do_not_kill_a_valid_job(self):
        message = ('level=warning msg="ReportLog error: unavailable: connection reset"\n'
                   'level=warning msg="ReportState error: unauthenticated: session expired"\n'
                   'an application says unregistered runner\n')
        result, output = self.run_child(f'print({message!r}); print("completed")')
        self.assertEqual(result, 0)
        self.assertTrue(output.endswith(b'completed\n'))

    def test_revoked_reporting_loop_is_killed_even_if_term_is_ignored(self):
        for method in ('ReportLog', 'ReportState'):
            with self.subTest(method=method):
                message = (f'time="2026-09-06T15:36:15Z" level=warning msg="{method} '
                           'error: unauthenticated: unregistered runner" task_id=34')
                result, output = self.run_child(
                    'import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); '
                    f'print({message!r}, flush=True); time.sleep(30)')
                self.assertEqual(result, 1)
                self.assertIn(message.encode(), output)

    def test_diagnostic_split_between_pipe_reads_still_retires_runner(self):
        result, output = self.run_child(
            'import sys,time; sys.stdout.write(\'level=warning msg="ReportLog error: unauthenticated: \'); '
            'sys.stdout.flush(); time.sleep(0.1); '
            'print(\'unregistered runner" task_id=34\', flush=True); time.sleep(30)')
        self.assertEqual(result, 1)
        self.assertIn(b'unauthenticated: unregistered runner', output)

    def test_large_output_is_forwarded_before_revocation(self):
        result, output = self.run_child(
            'import time; print("x" * 300000); '
            'print(\'level=error msg="ReportState error: unauthenticated: unregistered runner"\', flush=True); '
            'time.sleep(30)')
        self.assertEqual(result, 1)
        self.assertTrue(output.startswith(b'x' * 300000 + b'\n'))

    def descendant_cleanup(self, revoke):
        with tempfile.TemporaryDirectory() as temporary:
            ready = Path(temporary) / 'child-ready'
            child = ('import signal,time; from pathlib import Path; '
                     'signal.signal(signal.SIGTERM, signal.SIG_IGN); '
                     f'Path({str(ready)!r}).write_text("ready"); time.sleep(30)')
            ending = ('print(\'level=warning msg="ReportLog error: unauthenticated: unregistered runner"\', flush=True); '
                      'time.sleep(30)') if revoke else 'sys.exit(0)'
            code = (
                'import subprocess,sys,time; '
                f'child=subprocess.Popen([sys.executable,"-c",{child!r}]); '
                'print(child.pid, flush=True); '
                f'from pathlib import Path\nwhile not Path({str(ready)!r}).exists(): time.sleep(0.01)\n'
                + ending)
            result, output = self.run_child(code)
            self.assertEqual(result, 1 if revoke else 0)
            pid = int(output.splitlines()[0])
            try:
                status = Path(f'/proc/{pid}/status')
                # An adopted zombie has terminated; PID 1 performs final reaping.
                deadline = time.monotonic() + 1
                while status.exists() and '\nState:\tZ ' not in status.read_text() and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertTrue(not status.exists() or '\nState:\tZ ' in status.read_text())
            finally:
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass

    def test_process_group_descendants_cannot_outlive_revoked_runner(self):
        self.descendant_cleanup(revoke=True)

    def test_runner_normal_exit_also_cleans_background_descendants(self):
        self.descendant_cleanup(revoke=False)

    def test_pod_termination_is_forwarded_and_bounded(self):
        child = ('import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); '
                 'print("ready", flush=True); time.sleep(30)')
        invoke = (f'import importlib.util; spec=importlib.util.spec_from_file_location("runner",{str(SCRIPT)!r}); '
                  'module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module); '
                  f'raise SystemExit(module.supervise([{sys.executable!r},"-u","-c",{child!r}],grace=0.1))')
        process = subprocess.Popen([sys.executable, '-u', '-c', invoke], stdout=subprocess.PIPE)
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                self.assertTrue(selector.select(3), 'child did not become ready')
            self.assertEqual(process.stdout.readline(), b'ready\n')
            process.send_signal(signal.SIGTERM)
            self.assertEqual(process.wait(timeout=3), 128 + signal.SIGTERM)
        finally:
            process.kill() if process.poll() is None else None
            process.wait(timeout=3)
            process.stdout.close()


if __name__ == '__main__':
    unittest.main()

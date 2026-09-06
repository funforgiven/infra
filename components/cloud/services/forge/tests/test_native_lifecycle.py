"""Canceled ephemeral enrollments release native capacity without guest access."""
import importlib.util
from pathlib import Path
import subprocess
import unittest
from unittest.mock import Mock, patch

spec = importlib.util.spec_from_file_location('broker_lifecycle', Path(__file__).resolve().parents[1] / 'native-broker.py')
broker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(broker)


class NativeLifecycle(unittest.TestCase):
    def test_missing_enrollment_has_shutdown_grace_and_live_enrollment_resets_it(self):
        forge = Mock()
        forge.call.side_effect = [None, None, {'id': 7}, None, None]
        lease = broker.RunnerLease(forge, 7)
        with patch.object(broker.time, 'monotonic', side_effect=[100, 100, 159, 200, 200, 260]):
            self.assertFalse(lease.expired())
            self.assertFalse(lease.expired())
            self.assertFalse(lease.expired())
            self.assertFalse(lease.expired())
            self.assertTrue(lease.expired())
        forge.call.assert_called_with('GET', '/7', missing=True)

    def test_mismatched_identity_and_api_error_are_not_disappearance(self):
        forge = Mock()
        forge.call.return_value = {'id': 8}
        with self.assertRaisesRegex(RuntimeError, 'identity'):
            broker.RunnerLease(forge, 7).expired()
        forge.call.side_effect = RuntimeError('API unavailable')
        with self.assertRaisesRegex(RuntimeError, 'API unavailable'):
            broker.RunnerLease(forge, 7).expired()

    def test_expired_lease_closes_only_its_owned_process(self):
        process = Mock()
        process.poll.return_value = None
        process.communicate.side_effect = subprocess.TimeoutExpired('fixture', 15)
        with patch.object(broker.subprocess, 'Popen', return_value=process), \
                patch.object(broker.RunnerLease, 'expired', return_value=True):
            broker.run_registered_process(Mock(), 7, ['fixture'], {'handle': 'test'})
        process.terminate.assert_called_once_with()
        process.wait.assert_called_once_with(timeout=20)
        process.kill.assert_not_called()

    def test_transient_monitoring_failure_does_not_terminate_active_connection(self):
        process = Mock(returncode=0)
        process.poll.return_value = 0
        process.communicate.side_effect = [subprocess.TimeoutExpired('fixture', 15),
                                           subprocess.TimeoutExpired('fixture', 15), None]
        forge = Mock()
        forge.call.side_effect = [broker.TransientRequestError('temporary fixture'), {'id': 7}]
        with patch.object(broker.subprocess, 'Popen', return_value=process):
            broker.run_registered_process(forge, 7, ['fixture'], {'handle': 'test'})
        self.assertEqual(process.communicate.call_count, 3)
        process.terminate.assert_not_called()
        process.kill.assert_not_called()

    def test_monitoring_outage_restarts_consecutive_missing_grace(self):
        forge = Mock()
        forge.call.side_effect = [None, broker.TransientRequestError('temporary fixture'), None, None]
        lease = broker.RunnerLease(forge, 7)
        with patch.object(broker.time, 'monotonic', side_effect=[100, 100, 300, 300, 359]):
            self.assertFalse(lease.expired())
            self.assertFalse(lease.expired())
            self.assertIsNone(lease.ended_at)
            self.assertFalse(lease.expired())
            self.assertFalse(lease.expired())

    def test_graceful_shutdown_does_not_terminate_finished_process(self):
        process = Mock(returncode=0)
        process.poll.return_value = 0
        with patch.object(broker.subprocess, 'Popen', return_value=process), \
                patch.object(broker.RunnerLease, 'expired') as expired:
            broker.run_registered_process(Mock(), 7, ['fixture'], {'handle': 'test'})
        expired.assert_not_called()
        process.terminate.assert_not_called()

    def test_external_interruption_also_terminates_connection(self):
        process = Mock()
        process.poll.return_value = None
        process.communicate.side_effect = InterruptedError('fixture')
        with patch.object(broker.subprocess, 'Popen', return_value=process):
            with self.assertRaises(InterruptedError):
                broker.run_registered_process(Mock(), 7, ['fixture'], {'handle': 'test'})
        process.terminate.assert_called_once_with()

    def test_unresponsive_owned_process_is_killed_after_grace(self):
        process = Mock()
        process.poll.return_value = None
        process.wait.side_effect = [subprocess.TimeoutExpired('fixture', 20), 0]
        broker.stop_process(process)
        process.terminate.assert_called_once_with()
        process.kill.assert_called_once_with()
        self.assertEqual([call.kwargs['timeout'] for call in process.wait.call_args_list], [20, 10])

    def test_retried_communication_does_not_resend_enrollment(self):
        process = Mock(returncode=0)
        process.poll.return_value = 0
        process.communicate.side_effect = [subprocess.TimeoutExpired('fixture', 15), None]
        with patch.object(broker.subprocess, 'Popen', return_value=process), \
                patch.object(broker.RunnerLease, 'expired', return_value=False):
            broker.run_registered_process(Mock(), 7, ['fixture'], {'handle': 'test'})
        self.assertIsNotNone(process.communicate.call_args_list[0].kwargs['input'])
        self.assertIsNone(process.communicate.call_args_list[1].kwargs['input'])


if __name__ == '__main__':
    unittest.main()

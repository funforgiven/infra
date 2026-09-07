"""Recover safe discovery reads without duplicating a runner registration."""
from http.client import IncompleteRead
import importlib.util
import io
import json
from pathlib import Path
import ssl
import unittest
from unittest.mock import Mock, patch
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('registration_recovery',
    ROOT.parents[3] / 'deployments/homelab/cloud/services/46-forge/register-job.py')
register = importlib.util.module_from_spec(spec)
spec.loader.exec_module(register)


class Clock:
    def __init__(self):
        self.value = 0
        self.pauses = []

    def sleep(self, seconds):
        self.pauses.append(seconds)
        self.value += seconds


class Response(io.BytesIO):
    status = 200


def unavailable(code=503):
    return urllib.error.HTTPError('https://forge.invalid', code, 'Unavailable', {}, None)


class RegistrationRecovery(unittest.TestCase):
    def call(self, opener, method='GET', deadline=180, clock=None):
        clock = clock or Clock()
        request = urllib.request.Request('https://forge.invalid/discovery', method=method)
        with patch.object(register.time, 'monotonic', side_effect=lambda: clock.value), \
                patch.object(register.time, 'sleep', side_effect=clock.sleep):
            return register.registration_request(opener, request, deadline)

    def test_100_second_maintenance_recovers_without_new_identity(self):
        opener = Mock()
        opener.open.side_effect = [*[unavailable() for _ in range(20)], Response(b'[{"id": 7}]')]
        clock = Clock()
        self.assertEqual(self.call(opener, clock=clock), [{'id': 7}])
        self.assertEqual(clock.value, 100)
        self.assertEqual(opener.open.call_count, 21)
        self.assertTrue(all(c.args[0].get_method() == 'GET' for c in opener.open.call_args_list))

    def test_shared_budget_stops_persistent_failure(self):
        opener = Mock()
        def fail(*args, **kwargs):
            raise unavailable()
        opener.open.side_effect = fail
        clock = Clock()
        with self.assertRaises(TimeoutError):
            self.call(opener, deadline=12, clock=clock)
        self.assertEqual(clock.value, 12)
        self.assertEqual([c.kwargs['timeout'] for c in opener.open.call_args_list], [12, 7, 2])
        self.assertEqual(clock.pauses, [5, 5, 2])

    def test_enrollment_writes_permissions_and_redirects_are_never_replayed(self):
        for method, code in [('POST', 503), ('DELETE', 503), ('GET', 403), ('GET', 302)]:
            with self.subTest(method=method, code=code):
                opener = Mock()
                opener.open.side_effect = unavailable(code)
                clock = Clock()
                with self.assertRaises(urllib.error.HTTPError):
                    self.call(opener, method=method, clock=clock)
                self.assertEqual(opener.open.call_count, 1)
                self.assertEqual(clock.pauses, [])

    def test_transient_connection_and_incomplete_read_can_recover(self):
        for failure in (urllib.error.URLError(TimeoutError()), ConnectionResetError(), IncompleteRead(b'')):
            with self.subTest(failure=type(failure).__name__):
                opener = Mock()
                opener.open.side_effect = [failure, Response(b'[]')]
                self.assertEqual(self.call(opener), [])
                self.assertEqual(opener.open.call_count, 2)

    def test_certificate_failure_malformed_data_and_cancellation_are_immediate(self):
        for failure, exception in (
                (urllib.error.URLError(ssl.SSLCertVerificationError()), urllib.error.URLError),
                (KeyboardInterrupt(), KeyboardInterrupt),
                (Response(b'not JSON'), json.JSONDecodeError)):
            with self.subTest(failure=type(failure).__name__):
                opener = Mock()
                opener.open.side_effect = [failure]
                clock = Clock()
                with self.assertRaises(exception):
                    self.call(opener, clock=clock)
                self.assertEqual(opener.open.call_count, 1)
                self.assertEqual(clock.pauses, [])


if __name__ == '__main__':
    unittest.main()

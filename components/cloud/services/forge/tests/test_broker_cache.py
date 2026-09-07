"""Cache authority, optional fallback, and native/Linux capability boundaries."""
import contextlib
from http.client import IncompleteRead
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import broker_cache as cache


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


host = load('cache_host', ROOT / 'macos/host-job.py')
native = load('cache_native', ROOT / 'native-broker.py')
register = load('cache_register', ROOT.parents[3] / 'deployments/homelab/cloud/services/46-forge/register-job.py')
launcher = load('cache_launcher', ROOT / 'linux-launcher.py')


class CacheAuthority(unittest.TestCase):
    def setUp(self):
        self.job = {'id': 83, 'attempt': 2, 'name': 'macos-native', 'status': 'waiting',
                    'runs_on': ['macos-x86_64'], 'handle': 'opaque-handle'}
        self.descriptor = {'repository': cache.REPOSITORY, 'job_id': 83, 'attempt': 2,
            'run_id': 22, 'head': 'a' * 40, 'event_name': 'pull_request', 'ref': 'refs/pull/120/head',
            'name': 'macos-native', 'runs_on': ['macos-x86_64']}
        self.lease = {'lease_id': 'b' * 32, 'actions_cache_url': 'https://cache.fahrican.com/' + 'c' * 64 + '/',
                      'cache_mode': 'broker-scoped-v1', 'expires_unix': 8200}

    def test_current_queue_attempt_is_used_without_increment(self):
        claim = cache.claim(cache.REPOSITORY, self.job, self.descriptor, 1000)
        self.assertEqual(claim['attempt'], 2)
        self.assertEqual(set(claim), {'repository', 'job_id', 'attempt', 'run_id', 'head', 'event_name', 'ref', 'cache_lane', 'expires_unix'})
        self.assertNotIn('task_id', claim)
        self.assertEqual(claim['expires_unix'], 8200)

    def test_claim_rejects_stale_cross_repository_and_cross_lane_descriptor(self):
        for change in ({'attempt': 1}, {'job_id': 84}, {'repository': 'other/repo'}, {'head': '../main'},
                       {'run_id': True}, {'name': 'linux-quality'}, {'runs_on': ['linux-x86_64']},
                       {'event_name': 'push', 'ref': 'refs/pull/120/head'}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                cache.claim(cache.REPOSITORY, self.job, {**self.descriptor, **change}, 1000)

    def test_claim_rejects_unallocated_zero_attempt_and_nonwaiting_assignment(self):
        for change in ({'attempt': 0}, {'attempt': True}, {'id': True}, {'status': 'running'},
                       {'runs_on': ['macos-x86_64', 'privileged']}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                cache.claim(cache.REPOSITORY, {**self.job, **change}, self.descriptor, 1000)

    def test_main_shared_scope_can_only_come_from_authoritative_push_descriptor(self):
        value = cache.claim(cache.REPOSITORY, self.job,
            {**self.descriptor, 'event_name': 'push', 'ref': 'refs/heads/main'}, 1000)
        self.assertEqual((value['event_name'], value['ref']), ('push', 'refs/heads/main'))
        # PR claims cannot acquire main's shared writer scope.
        with self.assertRaises(ValueError):
            cache.claim(cache.REPOSITORY, self.job, {**self.descriptor, 'ref': 'refs/heads/main'}, 1000)

    def test_issue_uses_fixed_control_origins_and_authoritative_claims(self):
        broker = cache.CacheBroker()
        with patch.object(broker, 'request', side_effect=[self.descriptor, self.lease]) as request, \
                patch.object(cache.time, 'time', return_value=1000):
            self.assertEqual(broker.issue(cache.REPOSITORY, self.job), self.lease)
        self.assertEqual(request.call_args_list[0].args, ('GET', cache.DESCRIPTOR + '/v1/jobs/83?attempt=2'))
        self.assertEqual(request.call_args_list[1].args[1], cache.CONTROL + '/v1/leases')
        self.assertEqual(request.call_args_list[1].args[2]['head'], 'a' * 40)

    def test_missing_descriptor_and_cache_outage_warn_without_leaking_payloads(self):
        for responses in ([OSError('secret-credential')], [self.descriptor, OSError('secret-capability')],
                          [IncompleteRead(b'secret-capability')]):
            broker = cache.CacheBroker()
            with patch.object(broker, 'request', side_effect=responses), \
                    contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertIsNone(broker.issue(cache.REPOSITORY, self.job))
            self.assertIn('cold job', output.getvalue())
            self.assertNotIn('secret', output.getvalue())

    def test_signal_interruption_is_not_swallowed_as_optional_cache_failure(self):
        broker = cache.CacheBroker()
        with patch.object(broker, 'request', side_effect=InterruptedError('termination')):
            with self.assertRaises(InterruptedError):
                broker.issue(cache.REPOSITORY, self.job)

    def test_execution_only_and_aggregate_jobs_never_request_capabilities(self):
        broker = cache.CacheBroker()
        with patch.object(broker, 'request') as request:
            for name in ('windows-native', 'validation', 'macos-runtime-diagnostics'):
                self.assertIsNone(broker.issue(cache.REPOSITORY, {**self.job, 'name': name}))
        request.assert_not_called()

    def test_carrier_contains_no_broker_or_lease_identity(self):
        value = cache.carrier(self.lease, 1000)
        self.assertEqual(set(value), {'actions_cache_url', 'cache_mode', 'expires_unix'})
        for change in ({'actions_cache_url': 'https://evil.invalid/' + 'c' * 64 + '/'},
                       {'cache_mode': 'admin'}, {'expires_unix': 1000}, {'expires_unix': 8201}, {'expires_unix': True}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                cache.carrier({**self.lease, **change}, 1000)

    def test_revocation_is_fixed_origin_and_redacts_network_failure(self):
        broker = cache.CacheBroker()
        with patch.object(broker, 'request') as request:
            broker.revoke(self.lease['lease_id'])
            request.assert_called_once_with('DELETE', cache.CONTROL + '/v1/leases/' + 'b' * 32)
        with patch.object(broker, 'request', side_effect=OSError('private-token')), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            broker.revoke(self.lease['lease_id'])
        self.assertNotIn('private-token', output.getvalue())
        self.assertIn('expiry remains', output.getvalue())

    def test_native_cleanup_revokes_capability_even_if_runner_removal_fails(self):
        forge = Mock(repository=cache.REPOSITORY, prefix='forge-macos-job-')
        forge.call.side_effect = [{'uuid': 'uuid', 'token': 'token', 'id': 7}, RuntimeError('removal failed')]
        broker = Mock()
        broker.issue.return_value = self.lease
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, 'ssh-key').write_text('test-only')
            with patch.object(native, 'CacheBroker', return_value=broker), \
                    patch.object(native.time, 'time', return_value=1000), \
                    patch.object(native, 'run_registered_process') as run:
                with self.assertRaisesRegex(RuntimeError, 'removal failed'):
                    native.run_macos({'macos_known_hosts': '/fixed/known_hosts'}, Path(directory), forge, [self.job])
        broker.revoke.assert_called_once_with('b' * 32)
        self.assertEqual(run.call_args.args[-1]['cache'], cache.carrier(self.lease, 1000))

    def test_existing_mac_media_identity_and_cache_carrier_fit_and_validate(self):
        value = {'uuid': 'uuid', 'token': 'token', 'handle': 'handle', 'cache': cache.carrier(self.lease, 1000)}
        self.assertLess(len(json.dumps(value)), 16384)
        self.assertEqual(host.validate_enrollment(value, 1000), value)
        with contextlib.redirect_stdout(io.StringIO()) as output:
            cold = host.validate_enrollment({**value, 'cache': {'token': 'never-print'}}, 1000)
        self.assertEqual(set(cold), {'uuid', 'token', 'handle'})
        self.assertNotIn('never-print', output.getvalue())
        with self.assertRaises(ValueError):
            host.validate_enrollment({**value, 'command': 'execute-me'}, 1000)

    def test_linux_generated_config_contains_only_own_capability(self):
        base = 'runner:\n  env_file: ""\ncache:\n  enabled: false\n'
        output = register.runner_configuration(base, json.dumps(cache.carrier(self.lease, 1000)), 1000)
        envs = json.loads(next(line.split('envs: ', 1)[1] for line in output.splitlines() if 'envs: ' in line))
        self.assertEqual(set(envs), {'ACTIONS_CACHE_URL', 'FORGE_CACHE_MODE'})
        self.assertNotIn('lease_id', output)
        self.assertEqual(register.runner_configuration(base, None, 1000), base)
        with contextlib.redirect_stdout(io.StringIO()) as warning:
            self.assertEqual(register.runner_configuration(base, '{invalid-secret', 1000), base)
        self.assertNotIn('invalid-secret', warning.getvalue())

    def test_linux_job_preserves_handle_and_attempt_and_revokes_on_create_failure(self):
        assignment = {**self.job, 'name': 'linux-quality', 'runs_on': ['linux-x86_64']}
        completed = {'metadata': {'annotations': {cache.LEASE_ANNOTATION: 'd' * 32}},
                     'status': {'conditions': [{'type': 'Complete', 'status': 'True'}]}}
        template = {'spec': {'suspend': True, 'jobTemplate': {'spec': {
            'template': {'spec': {'initContainers': [{'env': []}]}}}}}}
        broker = Mock()
        broker.issue.return_value = self.lease
        calls = []

        def request(method, url, token, body=None, context=None):
            if method == 'POST':
                calls.append(body)
                raise RuntimeError('Kubernetes create failed')
            if '/cronjobs/' in url:
                return template
            if '/actions/runners/jobs' in url:
                return [assignment]
            return {'items': [completed]}

        with patch.object(launcher, 'Path'), patch.object(launcher.ssl, 'create_default_context'), \
                patch.object(launcher, 'CacheBroker', return_value=broker), \
                patch.object(launcher, 'request', side_effect=request), \
                patch.object(launcher.time, 'time', return_value=1000):
            with self.assertRaisesRegex(RuntimeError, 'Kubernetes create failed'):
                launcher.main()
        broker.issue.assert_called_once_with(cache.REPOSITORY, assignment)
        self.assertEqual([call.args[0] for call in broker.revoke.call_args_list], ['d' * 32, 'b' * 32])
        job = calls[0]
        self.assertEqual(job['metadata']['annotations'][launcher.ATTEMPT_ANNOTATION], '2')
        self.assertTrue(job['metadata']['name'].endswith('-83-2'))
        env = {entry['name']: entry['value'] for entry in job['spec']['template']['spec']['initContainers'][0]['env']}
        self.assertEqual(env['FORGE_JOB_HANDLE'], assignment['handle'])
        self.assertEqual(json.loads(env['FORGE_CACHE_CONFIG']), cache.carrier(self.lease, 1000))
        self.assertNotIn('lease_id', env['FORGE_CACHE_CONFIG'])


if __name__ == '__main__':
    unittest.main()

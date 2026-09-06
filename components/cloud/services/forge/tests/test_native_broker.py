"""Security and failure-boundary checks for the native VM controller."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

spec = importlib.util.spec_from_file_location('native_broker', Path(__file__).resolve().parents[1] / 'native-broker.py')
broker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(broker)


class CleanupBoundary(unittest.TestCase):
    def setUp(self):
        self.cloud = broker.Cloud({}, 'ci-project')
        self.vm = {'id': 'job-id', 'name': broker.PREFIX + '123-test', 'tenant_id': 'ci-project',
                   'metadata': {'managed_by': broker.MANAGER}}

    def test_never_deletes_unowned_or_cross_project_vm(self):
        for changed in ({'name': 'forge-macos'}, {'tenant_id': 'other-project'}, {'metadata': {}}):
            with self.subTest(changed=changed), patch.object(self.cloud, 'call') as call:
                with self.assertRaises(RuntimeError):
                    self.cloud.remove({**self.vm, **changed})
                call.assert_not_called()

    def test_retained_volume_aborts_before_server_deletion(self):
        with patch.object(self.cloud, 'call', return_value={'volumeAttachments': [
            {'volumeId': 'retained', 'delete_on_termination': False}]}) as call:
            with self.assertRaisesRegex(RuntimeError, 'retained disk'):
                self.cloud.remove(self.vm)
            self.assertFalse(any(args[0] == 'DELETE' for args, _ in call.call_args_list))

    def test_server_disappearance_is_not_enough_when_job_disk_remains(self):
        def api(method, base, path, *args, **kwargs):
            if path.endswith('/os-volume_attachments'):
                return {'volumeAttachments': [{'volumeId': 'job-disk', 'delete_on_termination': True}]}
            if base == broker.VOLUME:
                return {'volume': {'status': 'error_deleting'}}
            return None
        with patch.object(self.cloud, 'call', side_effect=api), patch.object(broker.time, 'sleep'):
            with self.assertRaisesRegex(RuntimeError, 'deletion did not finish'):
                self.cloud.remove(self.vm)

    def test_administrator_cloud_token_is_rejected(self):
        auth = {'token': {'project': {'id': 'ci-project'}, 'roles': [{'name': 'admin'}, {'name': 'member'}]}}
        with patch.object(broker, 'request', return_value=(auth, {'X-Subject-Token': 'test-only'})) as request:
            with self.assertRaisesRegex(RuntimeError, 'non-administrator'):
                self.cloud.call('GET', broker.COMPUTE, '/servers/detail')
            self.assertEqual(request.call_count, 1)

    def test_preparation_cleanup_refuses_foreign_or_attached_disks(self):
        owned = {'name': broker.PREFIX + 'disk', 'metadata': {
            'managed_by': broker.MANAGER, 'forge_project_id': 'ci-project'}, 'attachments': []}
        for changed in ({'name': 'retained-golden'}, {'metadata': {}},
                        {'attachments': [{'server_id': 'running-job'}]}):
            with self.subTest(changed=changed), patch.object(self.cloud, 'call',
                    return_value={'volume': {**owned, **changed}}) as call:
                with self.assertRaisesRegex(RuntimeError, 'unowned or attached'):
                    self.cloud.remove_volume('disk-id')
                self.assertFalse(any(args[0] == 'DELETE' for args, _ in call.call_args_list))

    def test_preparation_failure_cleans_disk_before_registering_runner(self):
        golden = {'id': 'golden', 'status': 'active', 'protected': True, 'visibility': 'private',
                  'owner': 'ci-project', 'image_role': 'forge-windows', 'image_source_revision': 'signed'}
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, 'forge-token').write_text('fixture')
            Path(directory, 'cloud-credential.json').write_text('{}')
            with patch.object(broker, 'Cloud', return_value=self.cloud), patch.object(broker, 'Forge') as forge, \
                    patch.object(self.cloud, 'reap'), patch.object(self.cloud, 'call',
                        side_effect=[golden, {'volume': {'id': 'preparation'}}]), \
                    patch.object(self.cloud, 'prepare_volume', side_effect=RuntimeError('preparation failed')), \
                    patch.object(self.cloud, 'remove_volume') as cleanup:
                forge.return_value.waiting.return_value = [{'id': 1, 'handle': 'fixture'}]
                forge.return_value.prefix = broker.PREFIX
                with self.assertRaisesRegex(RuntimeError, 'preparation failed'):
                    broker.run({'repository': 'forge-runner/runner-qualification', 'project_id': 'ci-project',
                                'windows_image_id': 'golden', 'windows_image_revision': 'signed'}, Path(directory))
                cleanup.assert_called_once_with('preparation')
                forge.return_value.call.assert_not_called()

    def test_preparation_cleanup_waits_for_nova_deletion_without_reissuing_it(self):
        deleting = {'volume': {'name': broker.PREFIX + 'disk', 'status': 'deleting',
                    'metadata': {'managed_by': broker.MANAGER, 'forge_project_id': 'ci-project'}, 'attachments': []}}
        with patch.object(self.cloud, 'call', side_effect=[deleting, None]) as call:
            self.cloud.remove_volume('disk-id')
            self.assertFalse(any(args[0] == 'DELETE' for args, _ in call.call_args_list))

    def test_cloud_microversions_are_scoped_to_the_target_service(self):
        self.cloud.headers = {'X-Auth-Token': 'test-only'}
        self.cloud.renew_at = float('inf')
        with patch.object(broker, 'request', return_value=({}, {})) as request:
            for base, version in ((broker.COMPUTE, 'compute 2.90'),
                                  (broker.VOLUME, 'volume 3.1'), (broker.IMAGE, None)):
                self.cloud.call('GET', base, '/qualification')
                self.assertEqual(request.call_args.args[2].get('OpenStack-API-Version'), version)
                self.assertEqual(request.call_args.args[2]['X-Auth-Token'], 'test-only')

    def test_application_repository_remains_blocked_during_qualification(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(broker, 'request') as request:
            with self.assertRaisesRegex(RuntimeError, 'qualification must finish'):
                broker.run({'repository': 'owner/application', 'qualification_only': True}, Path(directory))
            request.assert_not_called()

    def test_multi_repository_configuration_is_validated_before_credentials(self):
        entries = [
            {'repository': 'forge-runner/runner-qualification', 'token_file': 'forge-token'},
            {'repository': 'funforgiven/atollion', 'token_file': 'atollion-token'},
        ]
        with tempfile.TemporaryDirectory() as directory, patch.object(broker, 'Forge') as forge:
            with self.assertRaisesRegex(RuntimeError, 'qualification must finish'):
                broker.eligible_forges({'repositories': entries}, Path(directory))
            for invalid in ('../other/token', '/run/secret', '..'):
                with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                    broker.eligible_forges({'repositories': [{**entries[0], 'token_file': invalid}],
                                           'qualification_only': False}, Path(directory))
            with self.assertRaisesRegex(ValueError, 'duplicate'):
                broker.eligible_forges({'repositories': [entries[0], entries[0]],
                                       'qualification_only': False}, Path(directory))
            forge.assert_not_called()

    def test_enrolled_repositories_use_distinct_credentials(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(broker, 'Forge') as forge:
            Path(directory, 'qualification').write_text('qualification-fixture')
            Path(directory, 'atollion').write_text('atollion-fixture')
            broker.eligible_forges({'qualification_only': False, 'platform': 'macos', 'repositories': [
                {'repository': 'forge-runner/runner-qualification', 'token_file': 'qualification'},
                {'repository': 'funforgiven/atollion', 'token_file': 'atollion'},
            ]}, Path(directory))
            self.assertEqual([call.args for call in forge.call_args_list], [
                ('forge-runner/runner-qualification', 'qualification-fixture', 'macos'),
                ('funforgiven/atollion', 'atollion-fixture', 'macos')])

    def test_native_dispatch_picks_oldest_job_across_repositories(self):
        qualification, application = Mock(), Mock()
        qualification.waiting.return_value = [{'id': 20, 'handle': 'q'}]
        application.waiting.return_value = [{'id': 30, 'handle': 'later'}, {'id': 10, 'handle': 'first'}]
        repository, forge, jobs = broker.next_assignment([('qualification', qualification), ('application', application)])
        self.assertEqual((repository, forge, jobs), ('application', application, [{'id': 10, 'handle': 'first'}]))
        qualification.reap.assert_called_once()
        application.reap.assert_called_once()
        qualification.waiting.return_value = []
        application.waiting.return_value = []
        self.assertIsNone(broker.next_assignment([('qualification', qualification), ('application', application)]))


if __name__ == '__main__':
    unittest.main()

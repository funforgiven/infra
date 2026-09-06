"""Security and failure-boundary checks for the native VM controller."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

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


if __name__ == '__main__':
    unittest.main()

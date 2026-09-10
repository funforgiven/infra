import copy
import datetime
import importlib.util
import json
from pathlib import Path
import sys
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[5]
SCRIPTS = ROOT / 'deployments/homelab/cloud/services/46-forge'
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location('snapshot_backup', SCRIPTS / 'snapshot-backup.py')
backup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backup)


class FakeAPI:
    def __init__(self, offsite=False, fail_post=False):
        self.offsite, self.fail_post = offsite, fail_post
        self.deleted = []
        self.objects = {
            backup.JOB_PREFIX + '/forge-snapshot-backup-test': {
                'metadata': {'uid': '12345678-abcd-4321-abcd-123456789abc'},
                'spec': {'template': {'spec': {'volumes': [{'name': 'bootstrap', 'configMap': {'name': 'tools-hash'}}]}}}},
            backup.PVC_PREFIX + '/forgejo-data': {'status': {'phase': 'Bound'},
                'spec': {'resources': {'requests': {'storage': '80Gi'}}}},
        }

    def request(self, method, path, body=None, missing=False):
        if path.endswith('/velero/backups'):
            return {'items': [{'spec': {'includedNamespaces': ['forge']}, 'status': {'phase': 'InProgress'}}] if self.offsite else []}
        if method == 'GET':
            return copy.deepcopy(self.objects.get(path))
        if method == 'DELETE':
            self.deleted.append(path)
            assert body['preconditions']['uid'] == self.objects[path]['metadata']['uid']
            del self.objects[path]
            return {}
        value = copy.deepcopy(body)
        value['metadata']['uid'] = 'created-' + value['metadata']['name']
        value['status'] = {'readyToUse': True, 'creationTime': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'succeeded': 1}
        self.objects[path + '/' + value['metadata']['name']] = value
        if self.fail_post:
            self.fail_post = False
            raise TimeoutError('created but response lost')
        return value


class SnapshotControllerTests(unittest.TestCase):
    def setUp(self):
        self.template = json.loads((SCRIPTS / 'export-job.json').read_text())

    def test_opt_out_velero_policy_only_copies_the_recovery_volume(self):
        workload = next(d for d in yaml.safe_load_all((SCRIPTS / 'workloads.yaml').read_text())
                        if d['kind'] == 'StatefulSet')
        pod = workload['spec']['template']
        annotations = pod['metadata']['annotations']
        exclusions = set(annotations['backup.velero.io/backup-volumes-excludes'].split(','))
        # With global defaultVolumesToFsBackup=true, the opt-in annotation
        # alone is ignored. Include PVCs and emptyDirs in this independent check.
        eligible = {v['name'] for v in pod['spec']['volumes']
                    if 'persistentVolumeClaim' in v or 'emptyDir' in v}
        self.assertEqual(eligible - exclusions, {'backups'})
        self.assertEqual(annotations['backup.velero.io/backup-volumes'], 'backups')

    def test_export_cleanup_never_deletes_source_and_orders_readers_before_storage(self):
        api = FakeAPI()
        backup.run(api, 'forge-snapshot-backup-test', self.template)
        self.assertEqual(len(api.deleted), 4)
        self.assertTrue(api.deleted[0].endswith('-prune'))
        self.assertIn('/jobs/', api.deleted[1])
        self.assertIn('/persistentvolumeclaims/', api.deleted[2])
        self.assertIn('/volumesnapshots/', api.deleted[3])
        self.assertIn(backup.PVC_PREFIX + '/forgejo-data', api.objects)

    def test_lost_creation_response_still_cleans_own_snapshot(self):
        api = FakeAPI(fail_post=True)
        with self.assertRaises(TimeoutError):
            backup.run(api, 'forge-snapshot-backup-test', self.template)
        self.assertEqual(len(api.deleted), 1)
        self.assertIn('/volumesnapshots/', api.deleted[0])

    def test_active_offsite_preserves_files_and_creates_nothing(self):
        api = FakeAPI(offsite=True)
        with self.assertRaisesRegex(RuntimeError, 'Offsite'):
            backup.run(api, 'forge-snapshot-backup-test', self.template)
        self.assertEqual(len(api.objects), 2)
        self.assertFalse(api.deleted)

    def test_cleanup_rejects_foreign_resources_even_with_matching_name(self):
        api = FakeAPI()
        path = backup.PVC_PREFIX + '/forge-snapshot-foreign'
        api.objects[path] = {'metadata': {'uid': 'foreign', 'labels': {backup.LABEL: backup.MANAGER},
                                         'ownerReferences': [{'kind': 'Job', 'uid': 'another-owner'}]}}
        with self.assertRaisesRegex(RuntimeError, 'unowned'):
            backup.delete_owned(api, backup.PVC_PREFIX, 'forge-snapshot-foreign', 'our-owner')
        self.assertFalse(api.deleted)


if __name__ == '__main__':
    unittest.main()

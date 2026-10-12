import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import volume_plan


class TransferPlanning(unittest.TestCase):
    root = Path(__file__).resolve().parents[4]

    def test_all_captured_claims_can_export_read_only(self):
        inventory = json.loads((self.root / 'docs/migration/inventory-map.json').read_text())
        for claim in inventory['liveClaims']:
            with self.subTest(cluster=claim['sourceCluster'], namespace=claim['namespace'], claim=claim['name']):
                documents = volume_plan.render(self.root, claim['sourceCluster'], claim['namespace'], claim['name'], 'export')
                self.assertEqual(len(documents), 1)
                pod = documents[0]
                self.assertEqual(pod['spec']['volumes'][0]['persistentVolumeClaim'], {'claimName': claim['name'], 'readOnly': True})
                self.assertFalse(pod['spec']['automountServiceAccountToken'])
                self.assertTrue(pod['spec']['containers'][0]['volumeMounts'][0]['readOnly'])

    def test_media_uses_declared_cephfs_and_new_volume_identity(self):
        documents = volume_plan.render(self.root, 'services', 'media', 'media-library', 'restore', True)
        claim = documents[0]
        self.assertEqual(claim['kind'], 'PersistentVolumeClaim')
        self.assertEqual(claim['spec']['storageClassName'], 'ceph-filesystem')
        self.assertEqual(claim['spec']['accessModes'], ['ReadWriteMany'])
        self.assertNotIn('volumeName', claim['spec'])
        self.assertNotIn('selector', claim['spec'])

    def test_implicit_monitoring_claim_changes_namespace_and_driver(self):
        documents = volume_plan.render(self.root, 'infrastructure', 'observability', 'kube-prometheus-stack-grafana', 'restore', True)
        claim = documents[0]
        self.assertEqual(claim['metadata'], {'namespace': 'services-observability', 'name': 'kube-prometheus-stack-grafana'})
        self.assertEqual(claim['spec']['storageClassName'], 'ceph-block')
        self.assertEqual(claim['spec']['resources']['requests']['storage'], '10Gi')
        self.assertFalse(documents[1]['spec']['volumes'][0]['persistentVolumeClaim']['readOnly'])

    def test_cnpg_replica_data_and_retired_cloud_data_cannot_restore(self):
        for cluster, namespace, claim in [
            ('infrastructure', 'identity', 'zitadel-postgres-1'),
            ('services', 'netbird', 'netbird-postgres-1'),
            ('infrastructure', 'openstack', 'mysql-data-mariadb-server-0'),
            ('services', 'games-restore', 'data-factorio-0'),
        ]:
            with self.subTest(claim=claim):
                with self.assertRaises(ValueError):
                    volume_plan.render(self.root, cluster, namespace, claim, 'restore', True)

    def test_unifi_disk_restores_into_filesystem_claim_with_vm_held(self):
        documents = volume_plan.render_cloud(self.root, 'a7dbe35a-ddfa-41fe-ae76-13481f3bc8c6', True)
        self.assertEqual([item['kind'] for item in documents], ['PersistentVolumeClaim', 'Pod'])
        self.assertEqual(documents[0]['metadata']['name'], 'unifi-root')
        self.assertEqual(documents[0]['spec']['resources']['requests']['storage'], '80Gi')
        self.assertEqual(documents[0]['spec']['volumeMode'], 'Filesystem')
        self.assertEqual(documents[1]['spec']['volumes'][0]['persistentVolumeClaim']['claimName'], 'unifi-root')

    def test_unclaimed_cloud_device_cannot_be_promoted_to_guest(self):
        mapping = json.loads((self.root / 'docs/migration/inventory-map.json').read_text())
        identifier = next(item['id'] for item in mapping['cloudVolumes'] if item['action'] == 'archive-and-inspect-unclaimed-cloud-volume')
        with self.assertRaises(ValueError):
            volume_plan.render_cloud(self.root, identifier, True)

    def test_unknown_claim_and_source_replacement_refused(self):
        with self.assertRaises(ValueError):
            volume_plan.render(self.root, 'services', 'finance', 'invented', 'export')
        with self.assertRaises(ValueError):
            volume_plan.render(self.root, 'services', 'finance', 'wallos-database', 'export', True)


if __name__ == '__main__':
    unittest.main()

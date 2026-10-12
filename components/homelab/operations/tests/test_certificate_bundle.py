"""Exercise one-time TLS recovery with generated keys and real OpenSSL checks."""
import base64
import copy
import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import yaml

OPERATIONS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPERATIONS))
import certificate_bundle as recovery


class CertificateRecovery(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        folder = Path(cls.directory.name)
        subprocess.run([
            'openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes',
            '-subj', '/CN=example.test', '-addext', 'subjectAltName=DNS:example.test',
            '-days', '1', '-keyout', str(folder / 'key'), '-out', str(folder / 'cert'),
        ], check=True, capture_output=True)
        cls.key = (folder / 'key').read_bytes()
        cls.cert = (folder / 'cert').read_bytes()
        cls.fingerprint = hashlib.sha256(recovery.openssl(['x509', '-outform', 'DER'], cls.cert)).hexdigest()

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / 'repository'
        folder = self.root / 'deployments/homelab/cluster/infrastructure/gateway'
        folder.mkdir(parents=True)
        self.snapshot = {'objects': []}
        self.plan = {'objects': []}
        for filename, name, namespace, source_cluster in [
            ('management.yaml', 'management-tls', 'network-services', 'undercloud'),
            ('gateway.yaml', 'services-tls', 'services-network', 'services'),
            ('public.yaml', 'matrix-public-tls', 'services-network', 'services'),
        ]:
            (folder / filename).write_text(yaml.safe_dump({
                'kind': 'Certificate', 'metadata': {'name': name, 'namespace': namespace},
                'spec': {'secretName': name, 'dnsNames': ['example.test'],
                         'issuerRef': {'name': 'retained-acme', 'kind': 'ClusterIssuer'}},
            }))
            self.add_source(source_cluster, namespace, name, 'kubernetes.io/tls')
        self.add_source('undercloud', 'cert-manager', 'letsencrypt-cloudflare-account', 'Opaque')
        self.add_source('undercloud', 'cnpg-system', 'cnpg-webhook-cert', 'kubernetes.io/tls', 'regenerate-cluster-certificate')

    def add_source(self, cluster, namespace, name, kind, action='seed-once-before-gateway'):
        data = {'tls.key': base64.b64encode(self.key).decode()}
        if kind == 'kubernetes.io/tls':
            data['tls.crt'] = base64.b64encode(self.cert).decode()
        self.snapshot['objects'].append({'sourceCluster': cluster, 'object': {
            'apiVersion': 'v1', 'kind': 'Secret', 'type': kind,
            'metadata': {'namespace': namespace, 'name': name, 'uid': 'source-uid',
                         'ownerReferences': [{'name': 'source-owner'}]}, 'data': data,
        }})
        self.plan['objects'].append({'sourceCluster': cluster, 'namespace': namespace,
                                     'name': name, 'action': action,
                                     'certificateSHA256': self.fingerprint,
                                     'target': {'namespace': namespace, 'name': name}})

    def test_only_approved_secrets_and_no_source_ownership(self):
        bundle = recovery.render(self.snapshot, self.plan, self.root)
        self.assertEqual(len(bundle['items']), 4)
        self.assertNotIn('cnpg-webhook-cert', [item['metadata']['name'] for item in bundle['items']])
        for item in bundle['items']:
            self.assertNotIn('uid', item['metadata'])
            self.assertNotIn('ownerReferences', item['metadata'])
            if item['type'] == 'kubernetes.io/tls':
                self.assertEqual(item['metadata']['annotations']['cert-manager.io/issuer-name'], 'retained-acme')

    def test_public_capture_fingerprint_required(self):
        self.plan['objects'][0]['certificateSHA256'] = '0' * 64
        with self.assertRaises(ValueError):
            recovery.render(self.snapshot, self.plan, self.root)

    def test_key_must_match_certificate(self):
        other = subprocess.run(['openssl', 'genpkey', '-algorithm', 'ED25519'], check=True, capture_output=True).stdout
        self.snapshot['objects'][0]['object']['data']['tls.key'] = base64.b64encode(other).decode()
        with self.assertRaises(ValueError):
            recovery.render(self.snapshot, self.plan, self.root)

    def test_certificate_must_cover_current_routes(self):
        path = self.root / 'deployments/homelab/cluster/infrastructure/gateway/management.yaml'
        document = yaml.safe_load(path.read_text())
        document['spec']['dnsNames'] = ['another.test']
        path.write_text(yaml.safe_dump(document))
        with self.assertRaises(ValueError):
            recovery.render(self.snapshot, self.plan, self.root)

    def test_duplicate_or_missing_source_refused(self):
        self.snapshot['objects'].append(copy.deepcopy(self.snapshot['objects'][0]))
        with self.assertRaises(ValueError):
            recovery.render(self.snapshot, self.plan, self.root)
        self.snapshot['objects'].pop()
        self.snapshot['objects'].pop(0)
        with self.assertRaises(KeyError):
            recovery.render(self.snapshot, self.plan, self.root)

    def test_private_output_and_overwrite_refusal(self):
        folder = Path(self.temporary.name) / 'private'
        output = folder / 'seed.yaml'
        recovery.write_private({'private': 'synthetic'}, output, self.root)
        self.assertEqual(output.stat().st_mode & 0o777, 0o600)
        self.assertEqual(folder.stat().st_mode & 0o777, 0o700)
        with self.assertRaises(FileExistsError):
            recovery.write_private({}, output, self.root)
        self.assertEqual(yaml.safe_load(output.read_text()), {'private': 'synthetic'})

    def test_no_output_in_git_or_shared_directory(self):
        with self.assertRaises(ValueError):
            recovery.write_private({}, self.root / 'seed.yaml', self.root)
        shared = Path(self.temporary.name) / 'shared'
        shared.mkdir()
        shared.chmod(0o755)
        with self.assertRaises(ValueError):
            recovery.write_private({}, shared / 'seed.yaml', self.root)


if __name__ == '__main__':
    unittest.main()

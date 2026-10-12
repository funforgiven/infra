"""Review policy boundaries as sample flows; physical datapath checks remain required."""
import ipaddress
from pathlib import Path
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[4]
CLUSTER = ROOT / 'deployments/homelab/cluster'

def canonical(key):
    return key.removeprefix('k8s:')

def selected(selector, labels):
    if any(labels.get(canonical(k)) != v for k, v in selector.get('matchLabels', {}).items()):
        return False
    for expr in selector.get('matchExpressions', []):
        value = labels.get(canonical(expr['key']))
        op = expr['operator']
        if op == 'In' and value not in expr['values']: return False
        if op == 'NotIn' and value in expr['values']: return False
        if op == 'Exists' and value is None: return False
        if op == 'DoesNotExist' and value is not None: return False
    return True

def endpoint(namespace, name=None, **labels):
    result = {'io.kubernetes.pod.namespace': namespace, **labels}
    if name: result['app.kubernetes.io/name'] = name
    return result

def matches(rule, direction, namespace, remote, address, port, protocol, entity):
    prefix = 'to' if direction == 'egress' else 'from'
    destinations = []
    for selector in rule.get(prefix + 'Endpoints', []):
        labels = selector.get('matchLabels', {})
        if not any(canonical(k) == 'io.kubernetes.pod.namespace' for k in labels):
            selector = {'matchLabels': {'io.kubernetes.pod.namespace': namespace, **labels},
                        'matchExpressions': selector.get('matchExpressions', [])}
        destinations.append(selected(selector, remote))
    for cidr in rule.get(prefix + 'CIDRSet', []):
        ip = ipaddress.ip_address(address)
        destinations.append(ip in ipaddress.ip_network(cidr['cidr']) and
                            not any(ip in ipaddress.ip_network(x) for x in cidr.get('except', [])))
    if prefix + 'Entities' in rule:
        destinations.append(entity in rule[prefix + 'Entities'])
    if destinations and not any(destinations): return False
    if 'toPorts' in rule:
        return any(str(port) == p['port'] and protocol == p.get('protocol', 'ANY')
                   for entry in rule['toPorts'] for p in entry['ports'])
    return True

class CiliumTargetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.policies = []
        for path in CLUSTER.rglob('*.yaml'):
            if 'vendor' in path.parts or path.name.endswith('.sops.yaml'): continue
            if 'CiliumNetworkPolicy' not in path.read_text(): continue
            cls.policies.extend(d for d in yaml.safe_load_all(path.read_text())
                                if d and d.get('kind') == 'CiliumNetworkPolicy')

    def permits(self, local, remote=None, address='8.8.8.8', port=443,
                direction='egress', protocol='TCP', entity=None):
        namespace = local['io.kubernetes.pod.namespace']
        policies = [p['spec'] for p in self.policies if p['metadata']['namespace'] == namespace
                    and selected(p['spec']['endpointSelector'], local)]
        self.assertTrue(policies, 'The sample endpoint has no declared Cilium boundary')
        remote = remote or {}
        for policy in policies:
            if any(matches(r, direction, namespace, remote, address, port, protocol, entity)
                   for r in policy.get(direction + 'Deny', [])): return False
        return any(matches(r, direction, namespace, remote, address, port, protocol, entity)
                   for p in policies for r in p.get(direction, []))

    def test_backup_controller_has_api_only_access_despite_forge_allowlist(self):
        controller = endpoint('forge', 'forge-snapshot-backup')
        self.assertTrue(self.permits(controller, address='10.21.20.10', port=6443, entity='kube-apiserver'))
        for port in (443, 587, 2222):
            self.assertFalse(self.permits(controller, port=port))
        self.assertFalse(self.permits(controller, address='10.21.20.131', port=443))
        self.assertFalse(self.permits(controller, direction='ingress', port=3000))

    def test_export_and_disposable_restore_pods_cannot_contact_any_network(self):
        for namespace, name in (('forge', 'forge-snapshot-export'),
                                ('forge-restore', 'verification'), ('matrix-restore', 'verification')):
            local = endpoint(namespace, name)
            for direction in ('ingress', 'egress'):
                for address, port, entity in (('8.8.8.8', 443, 'world'),
                                              ('10.21.20.10', 6443, 'kube-apiserver'),
                                              ('10.100.0.20', 53, 'cluster')):
                    self.assertFalse(self.permits(local, address=address, port=port, entity=entity, direction=direction))

    def test_ci_jobs_have_public_https_but_no_private_or_api_access(self):
        local = endpoint('forge-ci', 'forge-linux-job')
        self.assertTrue(self.permits(local, address='8.8.8.8', port=443))
        for address in ('169.254.169.254', '10.21.20.131', '10.100.0.20', '127.0.0.1', '192.168.1.1'):
            self.assertFalse(self.permits(local, address=address, port=443), address)
        self.assertFalse(self.permits(local, address='10.21.20.10', port=6443, entity='kube-apiserver'))
        self.assertFalse(self.permits(local, address='8.8.8.8', port=587))

    def test_forge_identity_route_selects_management_gateway_backend(self):
        local = endpoint('forge', 'forgejo')
        remote = endpoint('envoy-gateway-system',
                          **{'gateway.envoyproxy.io/owning-gateway-name': 'management',
                             'gateway.envoyproxy.io/owning-gateway-namespace': 'network-services'})
        self.assertTrue(self.permits(local, remote=remote, address='10.100.0.20', port=10443))
        remote['gateway.envoyproxy.io/owning-gateway-name'] = 'unapproved'
        self.assertFalse(self.permits(local, remote=remote, address='10.100.0.20', port=10443))

    def test_restore_controller_api_access_is_scoped_to_its_identity(self):
        controller = endpoint('backup-qualification', 'home-automation-restore')
        self.assertTrue(self.permits(controller, address='10.21.20.10', port=6443, entity='kube-apiserver'))
        self.assertFalse(self.permits(controller, address='10.21.20.10', port=6443, entity='host'))
        self.assertFalse(self.permits(controller, address='8.8.8.8', port=443))


if __name__ == '__main__':
    unittest.main()

#!/usr/bin/env python3
"""Render an inventoried claim transfer Pod/PVC; never contact a cluster.

Application/controller suspension and writer shutdown are execution gates.
This helper renders YAML only. It does not establish consistency or export data.
"""
import argparse
import json
from pathlib import Path
import re
import sys

import yaml

IMAGE = 'quay.io/ceph/ceph:v20.2.2@sha256:6b4b5ae33acd3d736eb26d2a19238bce71a22f9cfb99cca887ba6312d0957644'


def render(root, cluster, namespace, claim, direction, new_claim=False):
    mapping = json.loads((root / 'docs/migration/inventory-map.json').read_text())
    matches = [item for item in mapping['liveClaims']
               if (item['sourceCluster'], item['namespace'], item['name']) == (cluster, namespace, claim)]
    if len(matches) != 1:
        raise ValueError('claim is not uniquely inventoried')
    plan = matches[0]
    source = json.loads((root / 'docs/migration/live-volume-inventory.json').read_text())
    original = next(item for item in source[cluster + '_pvc']
                    if (item['metadata']['namespace'], item['metadata']['name']) == (namespace, claim))
    if original['spec'].get('volumeMode', 'Filesystem') != 'Filesystem':
        raise ValueError('raw block claim requires a block export procedure')
    documents = []
    if direction == 'restore':
        if not plan['target'] or plan['action'] not in {'filesystem-restore', 'database-recovery'}:
            raise ValueError('this source is archival/qualification data, not a target restore')
        if namespace in {'identity', 'netbird'}:
            raise ValueError('CNPG recovery creates its own claims; do not restore replica directories')
        namespace, claim = plan['target'].split('/', 1)
        if new_claim:
            spec = None
            for path in (root / 'deployments/homelab/cluster').rglob('*.yaml'):
                if '.sops.' in path.name or 'vendor' in path.parts:
                    continue
                content = path.read_text()
                if not re.search(r"^kind: PersistentVolumeClaim\s*$", content, re.MULTILINE):
                    continue
                for item in yaml.safe_load_all(content):
                    if item and item.get('kind') == 'PersistentVolumeClaim' and \
                            (item['metadata'].get('namespace'), item['metadata']['name']) == (namespace, claim):
                        if spec is not None:
                            raise ValueError('ambiguous declared target claim')
                        spec = item['spec']
            if spec is None:
                spec = {'accessModes': original['spec']['accessModes'], 'volumeMode': 'Filesystem',
                        'storageClassName': 'ceph-block',
                        'resources': {'requests': {'storage': plan['capacity']}}}
            if spec['storageClassName'] not in {'ceph-block', 'ceph-filesystem'} or spec.get('volumeName'):
                raise ValueError('target claim must provision a fresh direct-CSI volume')
            documents.append({'apiVersion': 'v1', 'kind': 'PersistentVolumeClaim',
                              'metadata': {'namespace': namespace, 'name': claim}, 'spec': spec})
    elif new_claim:
        raise ValueError('source claims already exist; never create a source replacement')
    documents.append(copy_pod(namespace, claim, direction))
    return documents


def copy_pod(namespace, claim, direction):
    capabilities = ['DAC_OVERRIDE'] if direction == 'export' else ['CHOWN', 'DAC_OVERRIDE', 'FOWNER', 'FSETID', 'SETFCAP']
    return {
        'apiVersion': 'v1', 'kind': 'Pod',
        'metadata': {'name': 'migration-copy', 'namespace': namespace,
                     'labels': {'app.kubernetes.io/name': 'migration-copy'}},
        'spec': {
            'restartPolicy': 'Never', 'automountServiceAccountToken': False,
            'securityContext': {'runAsUser': 0, 'runAsGroup': 0, 'seccompProfile': {'type': 'RuntimeDefault'}},
            'containers': [{
                'name': 'copy', 'image': IMAGE,
                'command': ['/bin/bash', '-c', 'exec sleep infinity'],
                'resources': {'requests': {'cpu': '10m', 'memory': '64Mi'}, 'limits': {'memory': '256Mi'}},
                'securityContext': {'allowPrivilegeEscalation': False, 'readOnlyRootFilesystem': True,
                                    'capabilities': {'drop': ['ALL'], 'add': capabilities}},
                'volumeMounts': [{'name': 'data', 'mountPath': '/data', 'readOnly': direction == 'export'},
                                 {'name': 'tmp', 'mountPath': '/tmp'}],
            }],
            'volumes': [{'name': 'data', 'persistentVolumeClaim': {'claimName': claim, 'readOnly': direction == 'export'}},
                        {'name': 'tmp', 'emptyDir': {'sizeLimit': '100Mi'}}],
        },
    }

def render_cloud(root, identifier, new_claim):
    mapping = json.loads((root / 'docs/migration/inventory-map.json').read_text())
    matches = [item for item in mapping['cloudVolumes'] if item['id'] == identifier]
    if len(matches) != 1 or matches[0]['action'] != 'cold-guest-disk-restore':
        raise ValueError('cloud device is not the retained guest restore source')
    namespace, claim = matches[0]['target'].split('/', 1)
    definitions = list(yaml.safe_load_all((root / 'deployments/homelab/cluster/apps/unifi/vm.yaml').read_text()))
    pvc = next(item for item in definitions if item['kind'] == 'PersistentVolumeClaim'
               and (item['metadata']['namespace'], item['metadata']['name']) == (namespace, claim))
    if pvc['spec'].get('volumeName') or pvc['spec'].get('volumeMode') != 'Filesystem' or pvc['spec']['storageClassName'] != 'ceph-block':
        raise ValueError('guest destination must be a fresh filesystem RBD claim')
    return ([pvc] if new_claim else []) + [copy_pod(namespace, claim, 'restore')]



def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repository-root', type=Path, default=Path.cwd())
    parser.add_argument('--source-cluster', choices=['services', 'infrastructure'])
    parser.add_argument('--namespace')
    parser.add_argument('--claim')
    parser.add_argument('--cloud-volume-id')
    parser.add_argument('--direction', choices=['export', 'restore'], required=True)
    parser.add_argument('--new-claim', action='store_true')
    args = parser.parse_args()
    if args.cloud_volume_id:
        if args.direction != 'restore' or any((args.source_cluster, args.namespace, args.claim)):
            raise ValueError('cloud disk restore cannot select a Kubernetes source claim')
        documents = render_cloud(args.repository_root, args.cloud_volume_id, args.new_claim)
    else:
        if not all((args.source_cluster, args.namespace, args.claim)):
            raise ValueError('source claim identity is required')
        documents = render(args.repository_root, args.source_cluster, args.namespace, args.claim, args.direction, args.new_claim)
    sys.stdout.write(yaml.safe_dump_all(documents, sort_keys=False))


if __name__ == '__main__':
    try:
        main()
    except Exception:
        raise SystemExit('Transfer-plan render failed; check the inventoried claim, direction and fresh-CSI destination. No cluster operation was attempted.') from None

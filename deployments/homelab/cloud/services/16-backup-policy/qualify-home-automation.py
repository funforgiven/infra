#!/usr/bin/env python3
"""Restore only the archive volume and run its offline verifier in isolation."""
import json
import os
from pathlib import Path
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

server = 'https://' + os.environ['KUBERNETES_SERVICE_HOST'] + ':' + os.environ['KUBERNETES_SERVICE_PORT_HTTPS']
account = Path('/var/run/secrets/kubernetes.io/serviceaccount')
context = ssl.create_default_context(cafile=account / 'ca.crt')
namespace = 'home-automation-restore'


def request(method, path, body=None, missing_ok=False):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(server + path, data=data, method=method,
                                 headers={'Authorization': 'Bearer ' + (account / 'token').read_text().strip(),
                                          'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, context=context, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        if missing_ok and error.code == 404:
            return None
        raise RuntimeError(f'Kubernetes {method} returned HTTP {error.code}') from None


def wait_for(check, seconds=1800):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if check():
            return
        time.sleep(5)
    raise TimeoutError('Restore qualification timed out')


selected_backup = os.environ.get('BACKUP_NAME')
if selected_backup:
    latest = request('GET', '/apis/velero.io/v1/namespaces/velero/backups/'
                     + urllib.parse.quote(selected_backup, safe=''))
else:
    backups = request('GET', '/apis/velero.io/v1/namespaces/velero/backups?labelSelector=velero.io%2Fschedule-name%3Dservices-daily')['items']
    if not backups:
        raise SystemExit('No scheduled backup is available')
    latest = max(backups, key=lambda item: item['metadata']['creationTimestamp'])
if latest.get('status', {}).get('phase') != 'Completed':
    raise SystemExit('Latest daily backup is incomplete; refusing an older fallback')
if 'home-automation' not in latest['spec']['includedNamespaces']:
    raise SystemExit('Latest backup predates automation backup enrollment')

for resource, name in [('pods', 'home-assistant-0'), ('persistentvolumeclaims', 'automation-backups')]:
    path = f'/api/v1/namespaces/{namespace}/{resource}/{name}'
    request('DELETE', path, {'propagationPolicy': 'Foreground'}, missing_ok=True)
    wait_for(lambda: request('GET', path, missing_ok=True) is None, seconds=600)

# Precreate only scratch storage. Velero's Pod action discovers the original
# pod's PVCs before resource modifiers run; explicitly exclude those resources
# so it can never recreate or bind the production state claim in this namespace.
request('POST', f'/api/v1/namespaces/{namespace}/persistentvolumeclaims', {
    'apiVersion': 'v1', 'kind': 'PersistentVolumeClaim',
    'metadata': {'name': 'automation-backups', 'namespace': namespace},
    'spec': {'accessModes': ['ReadWriteOnce'], 'storageClassName': 'automation-restore',
             'resources': {'requests': {'storage': '20Gi'}}},
})

restore_name = os.environ['JOB_NAME']
restore = {
    'apiVersion': 'velero.io/v1', 'kind': 'Restore',
    'metadata': {'name': restore_name, 'namespace': 'velero',
                 'labels': {'backup.fahrican.com/qualification': 'home-automation'}},
    'spec': {
        'backupName': latest['metadata']['name'],
        'includedNamespaces': ['home-automation'],
        'includedResources': ['pods'],
        'excludedResources': ['persistentvolumeclaims', 'persistentvolumes'],
        'labelSelector': {'matchLabels': {'backup.fahrican.com/verify': 'automation'}},
        'includeClusterResources': False,
        'namespaceMapping': {'home-automation': namespace}, 'restorePVs': True,
        'resourceModifier': {'kind': 'ConfigMap', 'name': 'automation-restore-modifiers'},
    },
}
request('POST', '/apis/velero.io/v1/namespaces/velero/restores', restore)


def restored():
    status = request('GET', f'/apis/velero.io/v1/namespaces/velero/restores/{restore_name}').get('status', {})
    phase = status.get('phase')
    if phase in ('Failed', 'PartiallyFailed', 'FailedValidation'):
        raise RuntimeError('Velero restore failed: ' + phase)
    return phase == 'Completed'


wait_for(restored)


def verified():
    pod = request('GET', f'/api/v1/namespaces/{namespace}/pods/home-assistant-0', missing_ok=True)
    if not pod:
        return False
    spec = pod['spec']
    if spec.get('hostNetwork') or spec.get('hostPID') or spec.get('automountServiceAccountToken'):
        raise RuntimeError('Restore isolation contract violated')
    if pod['metadata'].get('annotations', {}).get('k8s.v1.cni.cncf.io/networks'):
        raise RuntimeError('Restored verifier has a secondary network')
    phase = pod.get('status', {}).get('phase')
    if phase == 'Failed':
        raise RuntimeError('Offline archive verification failed')
    return phase == 'Succeeded'


wait_for(verified, seconds=900)
print('Verified automation recovery from B2 backup ' + latest['metadata']['name'])

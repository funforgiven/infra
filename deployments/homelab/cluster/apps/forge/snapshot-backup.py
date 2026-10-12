#!/usr/bin/env python3
"""Export a disposable CSI snapshot, without touching the live Forgejo pod."""
import copy
import datetime
import json
import os
from pathlib import Path
import re
import ssl
import sys
import time
import urllib.error
import urllib.request

from recovery_archive import export_snapshot, prune_archives

NAMESPACE = 'forge'
MANAGER = 'forge-snapshot-backup'
API_PREFIX = '/apis/snapshot.storage.k8s.io/v1/namespaces/forge/volumesnapshots'
PVC_PREFIX = '/api/v1/namespaces/forge/persistentvolumeclaims'
JOB_PREFIX = '/apis/batch/v1/namespaces/forge/jobs'
LABEL = 'app.kubernetes.io/managed-by'


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class Kubernetes:
    def __init__(self):
        service_account = Path('/var/run/secrets/kubernetes.io/serviceaccount')
        self.token = (service_account / 'token').read_text().strip()
        self.base = 'https://' + os.environ['KUBERNETES_SERVICE_HOST'] + ':' + os.environ['KUBERNETES_SERVICE_PORT']
        context = ssl.create_default_context(cafile=str(service_account / 'ca.crt'))
        self.opener = urllib.request.build_opener(NoRedirect(), urllib.request.HTTPSHandler(context=context))

    def request(self, method, path, body=None, missing=False):
        request = urllib.request.Request(self.base + path, method=method,
            headers={'Authorization': 'Bearer ' + self.token, 'Content-Type': 'application/json'},
            data=json.dumps(body).encode() if body is not None else None)
        try:
            with self.opener.open(request, timeout=30) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            if missing and error.code == 404:
                return None
            raise RuntimeError(f'Kubernetes {method} {path.split("?")[0]}: HTTP {error.code}') from None


def active_offsite(api):
    backups = api.request('GET', '/apis/velero.io/v1/namespaces/velero/backups')['items']
    finished = {'Completed', 'PartiallyFailed', 'Failed', 'FailedValidation', 'Deleting'}
    return any(b.get('status', {}).get('phase', 'New') not in finished and
               (not b['spec'].get('includedNamespaces') or
                set(b['spec']['includedNamespaces']) & {'forge', '*'}) for b in backups)


def wait_for(api, path, ready, timeout=900):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = api.request('GET', path)
        if value.get('status', {}).get('error'):
            raise RuntimeError('Storage snapshot reported an error')
        if any(c['type'] == 'Failed' and c['status'] == 'True' for c in value.get('status', {}).get('conditions', [])):
            raise RuntimeError('Snapshot export Job failed; inspect its logs')
        if ready(value):
            return value
        time.sleep(10)
    raise TimeoutError('Timed out waiting for ' + path)


def delete_owned(api, path, name, owner_uid):
    value = api.request('GET', path + '/' + name, missing=True)
    if value is None:
        return
    metadata = value['metadata']
    if (not name.startswith('forge-snapshot-') or metadata.get('labels', {}).get(LABEL) != MANAGER or
            not any(o['uid'] == owner_uid and o['kind'] == 'Job' for o in metadata.get('ownerReferences', []))):
        raise RuntimeError('Refusing cleanup of an unowned snapshot resource')
    api.request('DELETE', path + '/' + name, {'apiVersion': 'v1', 'kind': 'DeleteOptions',
                'preconditions': {'uid': metadata['uid']}, 'propagationPolicy': 'Foreground'}, missing=True)
    deadline = time.monotonic() + 300
    while api.request('GET', path + '/' + name, missing=True) is not None:
        if time.monotonic() >= deadline:
            raise TimeoutError('Snapshot cleanup did not finish: ' + name)
        time.sleep(5)


def run(api, job_name, template):
    if not re.fullmatch(r'forge-snapshot-backup-[a-z0-9-]+', job_name):
        raise ValueError('Unexpected controller Job name')
    parent = api.request('GET', JOB_PREFIX + '/' + job_name)
    owner_uid = parent['metadata']['uid']
    template = copy.deepcopy(template)
    tools = next(v['configMap']['name'] for v in parent['spec']['template']['spec']['volumes'] if v['name'] == 'bootstrap')
    next(v for v in template['spec']['template']['spec']['volumes'] if v['name'] == 'bootstrap')['configMap']['name'] = tools
    name = 'forge-snapshot-' + owner_uid[:12]
    owner = {'apiVersion': 'batch/v1', 'kind': 'Job', 'name': job_name, 'uid': owner_uid}
    metadata = {'name': name, 'namespace': NAMESPACE,
                'labels': {LABEL: MANAGER, 'velero.io/exclude-from-backup': 'true'}, 'ownerReferences': [owner]}
    if active_offsite(api):
        raise RuntimeError('Offsite backup is active; retry the online snapshot later')
    source = api.request('GET', PVC_PREFIX + '/forgejo-data')
    if source['status']['phase'] != 'Bound':
        raise RuntimeError('Forgejo source volume is not bound')
    resources = []
    try:
        # Register intended cleanup before POST: an API timeout can occur after
        # creation. UID and owner checks make the eventual cleanup fail closed.
        resources.append((API_PREFIX, name))
        api.request('POST', API_PREFIX, {'apiVersion': 'snapshot.storage.k8s.io/v1', 'kind': 'VolumeSnapshot',
                    'metadata': metadata, 'spec': {'volumeSnapshotClassName': 'forge-online-backup',
                    'source': {'persistentVolumeClaimName': 'forgejo-data'}}})
        snapshot = wait_for(api, API_PREFIX + '/' + name, lambda s: s.get('status', {}).get('readyToUse') is True)
        captured = int(datetime.datetime.fromisoformat(snapshot['status']['creationTime'].replace('Z', '+00:00')).timestamp())
        print('Online storage snapshot ready: ' + name, flush=True)
        resources.append((PVC_PREFIX, name))
        api.request('POST', PVC_PREFIX, {'apiVersion': 'v1', 'kind': 'PersistentVolumeClaim', 'metadata': metadata,
                    'spec': {'accessModes': ['ReadWriteOnce'], 'storageClassName': 'forge-backup-scratch',
                    'resources': {'requests': {'storage': source['spec']['resources']['requests']['storage']}},
                    'dataSource': {'apiGroup': 'snapshot.storage.k8s.io', 'kind': 'VolumeSnapshot', 'name': name}}})
        job = copy.deepcopy(template)
        job['metadata'] = metadata
        pod = job['spec']['template']['spec']
        next(v for v in pod['volumes'] if v['name'] == 'snapshot')['persistentVolumeClaim']['claimName'] = name
        pod['containers'][0]['args'] = ['--export', snapshot['metadata']['uid'], str(captured)]
        resources.append((JOB_PREFIX, name))
        api.request('POST', JOB_PREFIX, job)
        wait_for(api, JOB_PREFIX + '/' + name, lambda j: j.get('status', {}).get('succeeded', 0) == 1, timeout=2400)
        # Velero must finish reading retained files before any pruning begins.
        # A concurrent offsite run simply defers retention to the next export.
        if not active_offsite(api):
            prune = copy.deepcopy(template)
            prune_name = name + '-prune'
            prune['metadata'] = {**metadata, 'name': prune_name}
            pod = prune['spec']['template']['spec']
            pod['volumes'] = [v for v in pod['volumes'] if v['name'] != 'snapshot']
            pod['containers'][0]['volumeMounts'] = [v for v in pod['containers'][0]['volumeMounts'] if v['name'] != 'snapshot']
            pod['containers'][0]['args'] = ['--prune']
            resources.append((JOB_PREFIX, prune_name))
            api.request('POST', JOB_PREFIX, prune)
            wait_for(api, JOB_PREFIX + '/' + prune_name, lambda j: j.get('status', {}).get('succeeded', 0) == 1, timeout=300)
    finally:
        # Stop readers before deleting the clone and then its source snapshot.
        # Failure stops cleanup; owner references and the parent TTL provide a
        # second cleanup path, while the failed controller remains observable.
        for path, resource_name in reversed(resources):
            delete_owned(api, path, resource_name, owner_uid)
    print('Online export complete; temporary snapshot, volume and Jobs removed.', flush=True)


if __name__ == '__main__':
    if sys.argv[1:2] == ['--export'] and len(sys.argv) == 4:
        export_snapshot(Path('/snapshot'), Path('/backups'), sys.argv[2], int(sys.argv[3]))
    elif sys.argv[1:] == ['--prune']:
        prune_archives(Path('/backups'))
    elif len(sys.argv) == 1:
        run(Kubernetes(), os.environ['JOB_NAME'], json.loads(Path('/bootstrap/export-job.json').read_text()))
    else:
        raise ValueError('Unsupported backup invocation')

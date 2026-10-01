"""Release only the explicitly identified disposable Forgejo restore copies."""
import time


TARGET = '/api/v1/namespaces/forge-restore/'


def cleanup(api):
    resources = []
    for name in ('forgejo-data', 'forgejo-backups'):
        path = TARGET + 'persistentvolumeclaims/' + name
        pvc = api('GET', path, missing_ok=True)
        if pvc is None:
            continue
        metadata, spec = pvc['metadata'], pvc['spec']
        if (metadata['namespace'] != 'forge-restore' or metadata['name'] != name or
                spec.get('storageClassName') != 'forge-restore' or
                not metadata.get('labels', {}).get('velero.io/restore-name', '').startswith('forge-qualification-')):
            raise RuntimeError('Refusing cleanup of an unrecognized restore claim')
        pv_path = None
        if spec.get('volumeName'):
            pv_path = '/api/v1/persistentvolumes/' + spec['volumeName']
            pv = api('GET', pv_path)
            ref = pv['spec'].get('claimRef', {})
            if (ref.get('namespace') != 'forge-restore' or ref.get('name') != name or
                    ref.get('uid') != metadata['uid'] or
                    pv['spec'].get('storageClassName') != 'forge-restore'):
                raise RuntimeError('Refusing cleanup of a volume outside this restore')
            # Velero's finalizer copies Retain from the production backup.
            # JSON Patch tests prevent changing a concurrently rebound volume.
            patch = [{'op': 'test', 'path': '/metadata/uid', 'value': pv['metadata']['uid']},
                     {'op': 'test', 'path': '/spec/claimRef', 'value': ref},
                     {'op': 'replace', 'path': '/spec/persistentVolumeReclaimPolicy', 'value': 'Delete'}]
        else:
            patch = None
        resources.append((path, metadata['uid'], pv_path, patch))

    def wait_absent(path):
        deadline = time.monotonic() + 300
        while api('GET', path, missing_ok=True) is not None:
            if time.monotonic() > deadline:
                raise TimeoutError('Disposable restore resource is still terminating: ' + path)
            time.sleep(5)

    pod_path = TARGET + 'pods/forgejo-0'
    pod = api('GET', pod_path, missing_ok=True)
    if pod is not None:
        if pod['metadata'].get('labels', {}).get('app.kubernetes.io/name') != 'forge-restore':
            raise RuntimeError('Refusing cleanup of a non-verifier pod')
        api('DELETE', pod_path, {'propagationPolicy': 'Foreground',
            'preconditions': {'uid': pod['metadata']['uid']}}, missing_ok=True)
        wait_absent(pod_path)
    for path, uid, pv_path, patch in resources:
        if pv_path:
            api('PATCH', pv_path, patch)
        api('DELETE', path, {'propagationPolicy': 'Foreground',
            'preconditions': {'uid': uid}}, missing_ok=True)
        wait_absent(path)
        if pv_path:
            wait_absent(pv_path)

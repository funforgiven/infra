#!/usr/bin/env python3
"""Create separate, encrypted native-controller credentials for qualification.

Run in the infrastructure development shell. Cloud administrator credentials
are used only for enrollment; controllers receive a CI-project member and TPM-secret creator token.
"""
import datetime
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile

import requests
import yaml

spec = importlib.util.spec_from_file_location('enroll', Path(__file__).with_name('enroll-runners.py'))
enroll = importlib.util.module_from_spec(spec)
spec.loader.exec_module(enroll)
ROOT = enroll.ROOT
IDENTITY = 'https://identity.cloud.fahrican.com/v3'


def checked(session, method, path, body=None):
    response = session.request(method, IDENTITY + path, json=body, timeout=30)
    if response.status_code not in (200, 201, 204):
        raise RuntimeError(f'Keystone enrollment failed: HTTP {response.status_code}')
    return response


def main():
    values = enroll.read(ROOT / 'runtime.sops.yaml')['stringData']
    forge = requests.Session()
    forge.auth = ('forge-runner', values['forgejo-runner-password'])
    for platform in ('windows', 'macos'):
        name = 'native-' + platform + '-qualification'
        target = ROOT / (name + '.sops.yaml')
        if target.exists():
            print(name + ': encrypted credential already exists')
            continue
        token = enroll.call(forge, 'POST', '/users/forge-runner/tokens', {
            'name': name, 'scopes': ['write:repository'],
            'repositories': [{'owner': 'forge-runner', 'name': 'runner-qualification'}]})
        application, cloud, user_id = None, None, None
        try:
            data = {'forge-token': token['sha1']}
            annotations = {}
            if platform == 'windows':
                source = enroll.read(Path('deployments/homelab/cloud/undercloud/71-magnum/secrets.sops.yaml'))
                keystone = yaml.safe_load(source['stringData']['values.yaml'])['endpoints']['identity']['auth']['admin']
                cloud = requests.Session()
                auth = checked(cloud, 'POST', '/auth/tokens', {'auth': {
                    'identity': {'methods': ['password'], 'password': {'user': {'name': 'admin',
                        'domain': {'name': 'Default'}, 'password': keystone['password']}}},
                    'scope': {'project': {'name': 'forge-ci', 'domain': {'name': 'Default'}}}}})
                cloud.headers['X-Auth-Token'] = auth.headers['X-Subject-Token']
                identity = auth.json()['token']
                if not {'member', 'creator'} <= {role['name'] for role in identity['roles']}:
                    raise RuntimeError('Reconcile the explicit CI member and Barbican creator roles before enrollment')
                user_id = identity['user']['id']
                expiry = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=365)).strftime('%Y-%m-%dT%H:%M:%SZ')
                application = checked(cloud, 'POST', '/users/' + user_id + '/application_credentials', {
                    'application_credential': {'name': name, 'description': 'Disposable Forgejo Windows jobs in forge-ci only',
                        'roles': [{'name': 'member'}, {'name': 'creator'}], 'expires_at': expiry, 'unrestricted': False}}).json()['application_credential']
                credential = {key: application[key] for key in ('id', 'secret')}
                verification = checked(requests.Session(), 'POST', '/auth/tokens', {'auth': {'identity': {
                    'methods': ['application_credential'], 'application_credential': credential}}}).json()['token']
                roles = {role['name'] for role in verification['roles']}
                # Keystone may add the reader role implied by member.
                if (not {'member', 'creator'} <= roles or not roles <= {'member', 'creator', 'reader'}
                        or verification['project']['id'] != identity['project']['id']):
                    raise RuntimeError('Enrolled credential exceeded the required CI member scope')
                data['cloud-credential.json'] = json.dumps(credential)
                annotations['forge.fahrican.com/cloud-credential-expires'] = expiry
                (ROOT / 'native-status.json').write_text(json.dumps({'windows_cloud_credential_expires': expiry}, indent=2) + '\n')
            else:
                public_path = Path(__file__).parent / 'macos/broker.pub'
                if public_path.exists():
                    raise RuntimeError('Broker public key exists without its encrypted credential; inspect before replacing it')
                with tempfile.TemporaryDirectory(prefix='forge-macos-broker-') as directory:
                    key = Path(directory) / 'id_ed25519'
                    subprocess.run(['ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-C', 'forge-native-macos-broker', '-f', str(key)], check=True)
                    data['ssh-key'] = key.read_text()
                    public_key = key.with_suffix('.pub').read_text()
            document = {'apiVersion': 'v1', 'kind': 'Secret', 'metadata': {'name': name,
                'namespace': 'forge-control', 'annotations': annotations,
                'labels': {'velero.io/exclude-from-backup': 'true'}}, 'type': 'Opaque', 'stringData': data}
            enroll.save(target, document)
            if platform == 'macos':
                public_path.write_text(public_key)
            print(name + ': created, scope-checked and encrypted')
        except Exception:
            enroll.call(forge, 'DELETE', '/users/forge-runner/tokens/' + str(token['id']))
            if application is not None:
                checked(cloud, 'DELETE', '/users/' + user_id + '/application_credentials/' + application['id'])
            raise


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print('Native enrollment failed:', str(error) if isinstance(error, RuntimeError) else type(error).__name__)
        raise SystemExit(1) from None

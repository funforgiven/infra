#!/usr/bin/env python3
"""Install/recover the Rooftrollen dashboard through Home Assistant's APIs.

Requires Python with PyYAML, requests and websocket-client, plus kubectl and sops.
Use a services-cluster kubeconfig. The encrypted HA credential stays in memory.
The first installation may need one Home Assistant restart to register /local.
"""

import argparse
import base64
import datetime
import hashlib
import json
from pathlib import Path
import re
import subprocess

import requests
import websocket
import yaml

ROOT = Path(__file__).resolve().parent
URL_PATH = 'dashboard-rooftrollen'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kubeconfig', required=True)
    parser.add_argument('--credentials', default='secrets/home-assistant.yaml')
    parser.add_argument('--kubectl', default='kubectl')
    parser.add_argument('--sops', default='sops')
    parser.add_argument('--set-user-default', action='store_true', help='Open Rooftrollen by default for this user and follow system light/dark mode')
    args = parser.parse_args()

    config = yaml.safe_load((ROOT / 'dashboard.yaml').read_text())
    theme = yaml.safe_load((ROOT / 'theme.yaml').read_text())
    assets = json.loads((ROOT / 'assets.json').read_text())
    credentials = yaml.safe_load(subprocess.check_output(
        [args.sops, '-d', args.credentials]))['home_assistant']
    url = credentials['url'].rstrip('/')
    http = requests.Session()
    http.headers['Authorization'] = 'Bearer ' + credentials['long_lived_token']
    socket = websocket.create_connection(url.replace('https://', 'wss://') + '/api/websocket', timeout=30)
    socket.recv()
    socket.send(json.dumps({'type': 'auth', 'access_token': credentials['long_lived_token']}))
    if json.loads(socket.recv()).get('type') != 'auth_ok':
        raise RuntimeError('Home Assistant authentication failed')
    request_id = 0

    def ws(command, **data):
        nonlocal request_id
        request_id += 1
        socket.send(json.dumps({'id': request_id, 'type': command, **data}))
        while True:
            response = json.loads(socket.recv())
            if response.get('id') == request_id and response.get('type') == 'result':
                if not response['success']:
                    raise RuntimeError(f'{command}: {response.get("error")}')
                return response.get('result')

    def post(path, data):
        response = http.post(url + '/api/' + path, json=data, timeout=30)
        response.raise_for_status()
        return response.json()

    def remote(code, payload):
        return subprocess.check_output([
            args.kubectl, '--kubeconfig', args.kubeconfig, '-n', 'home-automation',
            'exec', '-i', 'home-assistant-0', '-c', 'home-assistant', '--', 'python3', '-c', code,
        ], input=json.dumps(payload).encode())

    # Resolve every referenced entity before installing any live configuration.
    response = http.get(url + '/api/states', timeout=30)
    response.raise_for_status()
    entities = {state['entity_id'] for state in response.json()}
    references = set(re.findall(r'\b(?:light|switch|climate|lock|sensor|binary_sensor|automation|event|person|weather)\.[a-z0-9_]+', json.dumps(config)))
    missing = references - entities - {'light.turn_off', 'lock.lock', 'lock.unlock', 'lock.open'}
    if missing:
        raise RuntimeError('Dashboard entities do not exist: ' + ', '.join(sorted(missing)))

    # Download public assets without the authenticated Home Assistant session.
    files = {'themes/rooftrollen.yaml': base64.b64encode((ROOT / 'theme.yaml').read_bytes()).decode()}
    for asset in assets:
        response = requests.get(asset['url'], timeout=60)
        response.raise_for_status()
        if hashlib.sha256(response.content).hexdigest() != asset['sha256']:
            raise RuntimeError('Checksum mismatch for ' + asset['asset'])
        files['www/rooftrollen/' + asset['asset']] = base64.b64encode(response.content).decode()

    dashboards = ws('lovelace/dashboards/list')
    existing = next((d for d in dashboards if d['url_path'] == URL_PATH), None)
    backup = {'dashboards': dashboards, 'resources': ws('lovelace/resources'), 'themes': ws('frontend/get_themes')}
    if args.set_user_default:
        backup['user_core'] = ws('frontend/get_user_data', key='core')['value']
        backup['user_theme'] = ws('frontend/get_user_data', key='theme')['value']
    if existing:
        backup['dashboard'] = ws('lovelace/config', url_path=URL_PATH)
    stamp = datetime.datetime.now(datetime.UTC).strftime('%Y%m%dT%H%M%S%fZ')
    print(remote('''
import base64, json, os, sys
from pathlib import Path
os.umask(0o077)
p = json.load(sys.stdin)
root = Path('/config')
configuration = root / 'configuration.yaml'
old = configuration.read_text()
marker = 'themes: !include_dir_merge_named themes'
if '\\nfrontend:' in '\\n' + old and marker not in old:
    raise SystemExit('Existing frontend configuration needs its theme include merged before installation')
backup = root / '.dashboard-backups' / p['stamp']
backup.mkdir(parents=True)
(backup / 'configuration.yaml').write_text(old)
(backup / 'frontend.json').write_text(json.dumps(p['backup'], indent=2))
for name, content in p['files'].items():
    destination = root / name
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        previous = backup / name
        previous.parent.mkdir(parents=True, exist_ok=True)
        previous.write_bytes(destination.read_bytes())
    temporary = destination.with_suffix(destination.suffix + '.tmp')
    temporary.write_bytes(base64.b64decode(content))
    temporary.replace(destination)
if marker not in old:
    updated = old.rstrip() + '\\n\\n# Rooftrollen dashboard: adaptive light/dark theme.\\nfrontend:\\n  themes: !include_dir_merge_named themes\\n'
    temporary = root / 'configuration.yaml.tmp'
    temporary.write_text(updated)
    temporary.replace(configuration)
print('Frontend files installed; previous configuration: ' + str(backup))
''', {'files': files, 'stamp': stamp, 'backup': backup}).decode().strip())

    check = post('config/core/check_config', {})
    if check.get('result') != 'valid':
        raise RuntimeError('Home Assistant configuration check failed: ' + str(check))
    post('services/frontend/reload_themes', {})
    if ws('frontend/get_themes')['themes'].get('Rooftrollen') != theme['Rooftrollen']:
        raise RuntimeError('Theme readback did not match')

    resources = backup['resources']
    for asset in assets:
        asset_path = '/local/rooftrollen/' + asset['asset']
        resource_url = asset_path + '?v=' + asset['version'].removeprefix('v')
        existing_resource = next((r for r in resources if r['url'].split('?')[0] == asset_path), None)
        if existing_resource:
            if existing_resource['url'] != resource_url:
                ws('lovelace/resources/update', resource_id=existing_resource['id'], url=resource_url, res_type='module')
        else:
            ws('lovelace/resources/create', url=resource_url, res_type='module')
        fetched = http.get(url + asset_path, timeout=30)
        if fetched.status_code == 404:
            raise RuntimeError('Home Assistant has not registered /local yet. Restart Home Assistant once, then rerun this installer.')
        fetched.raise_for_status()
        if hashlib.sha256(fetched.content).hexdigest() != asset['sha256']:
            raise RuntimeError('Served resource does not match ' + asset['asset'])

    if not existing:
        ws('lovelace/dashboards/create', url_path=URL_PATH, title='Rooftrollen', icon='mdi:home-variant-outline',
           show_in_sidebar=True, require_admin=False)
    ws('lovelace/config/save', url_path=URL_PATH, config=config)
    if ws('lovelace/config', url_path=URL_PATH) != config:
        raise RuntimeError('Dashboard readback did not match')
    if args.set_user_default:
        core = {**(backup['user_core'] or {}), 'default_panel': URL_PATH}
        selected_theme = {**(backup['user_theme'] or {}), 'theme': 'Rooftrollen'}
        selected_theme.pop('dark', None)
        ws('frontend/set_user_data', key='core', value=core)
        ws('frontend/set_user_data', key='theme', value=selected_theme)
        if ws('frontend/get_user_data', key='core')['value'] != core or ws('frontend/get_user_data', key='theme')['value'] != selected_theme:
            raise RuntimeError('User dashboard/theme preference readback did not match')
    socket.close()
    print(f'Dashboard verified: {url}/{URL_PATH}/home')


if __name__ == '__main__':
    main()

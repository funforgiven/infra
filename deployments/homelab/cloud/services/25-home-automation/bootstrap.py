#!/usr/bin/env python3
"""Seed a new installation; preserve user settings and network identities."""
import datetime
import json
import os
from pathlib import Path
import shutil

os.umask(0o077)
state = Path('/state')
for name in ('home-assistant', 'matter', 'mosquitto', 'zigbee2mqtt'):
    (state / name).mkdir(exist_ok=True)
ha = state / 'home-assistant'
for name, initial in [('automations.yaml', '[]\n'), ('scripts.yaml', '{}\n'), ('scenes.yaml', '[]\n')]:
    if not (ha / name).exists():
        (ha / name).write_text(initial)
for source, destination in [('configuration.yaml', ha / 'configuration.yaml'),
                            ('zigbee-configuration.yaml', state / 'zigbee2mqtt/configuration.yaml')]:
    if not destination.exists():
        shutil.copyfile(Path('/bootstrap') / source, destination)

# HTTP settings moved from YAML to versioned storage in HA 2026.8. Seed once,
# using the pinned 2026.9.2 schema; subsequent changes belong to HA's UI.
(ha / '.storage').mkdir(exist_ok=True)
http = ha / '.storage/http'
if not http.exists():
    http.write_text(json.dumps({
        'version': 2, 'minor_version': 2, 'key': 'http',
        'data': {
            'stable': {
                'server_port': 8123, 'cors_allowed_origins': [],
                'use_x_forwarded_for': True,
                'trusted_proxies': ['172.16.0.0/13'],
                'ip_ban_enabled': True, 'login_attempts_threshold': 5,
                'ssl_profile': 'modern', 'use_x_frame_options': True,
                'created_at': datetime.datetime.now(datetime.UTC).isoformat(),
                'error': None, 'error_message': None,
            },
            'pending': None, 'yaml_migration_done': True,
        },
    }))

credentials = Path('/credentials')
runtime = Path('/runtime')
runtime.mkdir(exist_ok=True)
# Mosquitto's ACL reader requires a regular file; projected ConfigMaps use symlinks.
for name in ('mosquitto.acl', 'mosquitto-nuki.acl'):
    shutil.copyfile(Path('/bootstrap') / name, runtime / name)
for filename, users in (
    ('mosquitto-passwords', ('homeassistant', 'zigbee2mqtt', 'monitoring')),
    ('nuki-passwords', ('nuki',)),
):
    with (runtime / filename).open('w') as output:
        for user in users:
            password = (credentials / f'{user}-password').read_text().strip()
            if not password or any(c in password for c in '\r\n:'):
                raise SystemExit('Invalid MQTT credential')
            output.write(f'{user}:{password}\n')
print('Initial configuration and runtime credentials prepared.')

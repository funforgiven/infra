#!/usr/bin/env python3
"""Install the two fixed RODECaster actions using encrypted webhook credentials.

The webhook IDs exist only in the workstation SOPS file, so these automations
stay UI-owned (automations.yaml) instead of joining the Git-owned managed/ set.
"""

import argparse
import json
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit

import requests
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[5] / 'components/homelab/operations'))
from encrypted_inputs import decrypt  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ha-credentials', default='secrets/home-assistant.yaml')
    parser.add_argument('--midi-credentials', default='secrets/home-assistant-midi.yaml')
    args = parser.parse_args()

    ha = decrypt(args.ha_credentials)[0]['home_assistant']
    webhooks = json.loads(decrypt(args.midi_credentials)[0]['home_midi']['webhooks'])
    replacements = {}
    for action, marker in [('loft-light', '__LOFT_LIGHT_WEBHOOK_ID__'),
                           ('loft-airflow', '__LOFT_AIRFLOW_WEBHOOK_ID__')]:
        url = urlsplit(webhooks[action])
        if (url.scheme != 'https' or url.netloc != urlsplit(ha['url']).netloc
                or url.query or url.fragment
                or not re.fullmatch(r'/api/webhook/[A-Za-z0-9_-]{40,}', url.path)):
            raise ValueError('Invalid home-control credential')
        replacements[marker] = url.path.rsplit('/', 1)[1]

    http = requests.Session()
    http.headers['Authorization'] = 'Bearer ' + ha['long_lived_token']
    source = Path(__file__).with_name('rodecaster-midi-automations.yaml').read_text()
    for marker, value in replacements.items():
        source = source.replace(marker, value)
    automations = yaml.safe_load(source)
    for config in automations:
        endpoint = ha['url'].rstrip('/') + '/api/config/automation/config/' + config['id']
        response = http.post(endpoint, json=config, timeout=30)
        response.raise_for_status()
        response = http.get(endpoint, timeout=30)
        response.raise_for_status()
        if response.json() != config:
            raise RuntimeError('Automation readback mismatch: ' + config['id'])
        print('Installed and verified:', config['id'])


if __name__ == '__main__':
    main()

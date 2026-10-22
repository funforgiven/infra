#!/usr/bin/env python3
"""Install pinned third-party code before Home Assistant starts.

Every artifact is checksum-verified and kept on the state volume, so routine
restarts work offline. Only the daikin_onecta component and the dashboard's
frontend modules are managed; HA owns Onecta's credentials, tokens, options and
entity registry in .storage.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import tarfile
import tempfile
import urllib.request

VERSION = '4.6.19'
COMMIT = '719600642d2e21f02d87f4a570ce4580849f87b1'
SHA256 = '1cf35a3d44dfa71cc552948bf958c583c321a9a87a2c0fb81258be3921670b1a'
URL = f'https://codeload.github.com/jwillemsen/daikin_onecta/tar.gz/{COMMIT}'
MAX_ARCHIVE_BYTES = 8 * 1024 * 1024
# Lovelace modules served from /local/rooftrollen/; configuration.yaml pins the
# same versions in its resource URLs. Mushroom is Apache-2.0, card-mod is MIT.
FRONTEND = {
    'mushroom.js': ('https://github.com/piitaya/lovelace-mushroom/releases/download/v5.2.3/mushroom.js',
                    '631668268e474d5357e0f17f161322499ea5c93a910431477e112653d7aa456b'),
    'card-mod.js': ('https://raw.githubusercontent.com/thomasloven/lovelace-card-mod/v4.2.1/card-mod.js',
                    '5e7e71ad61796f59070f8c4621e69fa8e71a9864d0be0922bc4dbc72f990cd35'),
}


def fetch(url: str, sha256: str) -> bytes:
    with urllib.request.urlopen(url, timeout=45) as response:
        data = response.read(MAX_ARCHIVE_BYTES + 1)
    if len(data) > MAX_ARCHIVE_BYTES or hashlib.sha256(data).hexdigest() != sha256:
        raise ValueError('Checksum mismatch for ' + url)
    return data


def install_frontend(config: Path):
    www = config / 'www/rooftrollen'
    www.mkdir(parents=True, exist_ok=True)
    for name, (url, sha256) in FRONTEND.items():
        target = www / name
        if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() == sha256:
            continue
        partial = target.with_suffix('.partial')
        partial.write_bytes(fetch(url, sha256))
        os.replace(partial, target)
    print('Dashboard frontend modules verified.')


def install_onecta(config: Path, bootstrap: Path):
    cache = config / '.managed-integrations'
    cache.mkdir(parents=True, exist_ok=True)
    archive = cache / f'onecta-{SHA256}.tar.gz'
    if archive.exists() and hashlib.sha256(archive.read_bytes()).hexdigest() != SHA256:
        raise ValueError('Cached Onecta archive checksum mismatch')
    if not archive.exists():
        partial = archive.with_suffix('.partial')
        partial.write_bytes(fetch(URL, SHA256))
        os.replace(partial, archive)

    components = config / 'custom_components'
    components.mkdir(exist_ok=True)
    target = components / 'daikin_onecta'
    # Keep rollback outside custom_components so HA never discovers a second copy.
    previous = cache / 'daikin_onecta.previous'
    if previous.exists() and not target.exists():
        os.replace(previous, target)
    with tempfile.TemporaryDirectory(prefix='onecta-', dir=cache) as work:
        staging = Path(work) / 'daikin_onecta'
        staging.mkdir()
        prefix = f'daikin_onecta-{COMMIT}/custom_components/daikin_onecta/'
        with tarfile.open(archive, 'r:gz') as source:
            for member in source.getmembers():
                if not member.name.startswith(prefix) or member.isdir():
                    continue
                relative = Path(member.name.removeprefix(prefix))
                if not member.isfile() or relative.is_absolute() or '..' in relative.parts:
                    raise ValueError('Unsafe Onecta archive member')
                destination = staging / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                with source.extractfile(member) as content, destination.open('wb') as output:
                    shutil.copyfileobj(content, output)
            license_file = source.extractfile(f'daikin_onecta-{COMMIT}/LICENSE.TXT')
            (staging / 'LICENSE.TXT').write_bytes(license_file.read())
        manifest = json.loads((staging / 'manifest.json').read_text())
        if manifest['domain'] != 'daikin_onecta' or manifest['version'] != VERSION:
            raise ValueError('Unexpected Onecta release manifest')
        shutil.copyfile(bootstrap / 'onecta-application-credentials.py',
                        staging / 'application_credentials.py')
        for path in staging.rglob('*.py'):
            compile(path.read_bytes(), str(path), 'exec')
        if previous.exists():
            shutil.rmtree(previous)
        if target.exists():
            os.replace(target, previous)
        try:
            os.replace(staging, target)
        except OSError:
            if previous.exists():
                os.replace(previous, target)
            raise
        if previous.exists():
            shutil.rmtree(previous)
    print(f'Daikin Onecta {VERSION} installed with the direct OAuth callback.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=Path('/state/home-assistant'))
    parser.add_argument('--bootstrap', type=Path, default=Path('/bootstrap'))
    args = parser.parse_args()
    os.umask(0o077)
    install_onecta(args.config, args.bootstrap)
    install_frontend(args.config)

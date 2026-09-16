#!/usr/bin/env python3
"""Install the pinned Onecta component before Home Assistant starts.

Cache the verified release on the state volume so routine restarts work offline.
Only the managed daikin_onecta component is replaced; HA owns its credentials,
tokens, options and entity registry in .storage.
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


def install(config: Path, bootstrap: Path):
    os.umask(0o077)
    cache = config / '.managed-integrations'
    cache.mkdir(parents=True, exist_ok=True)
    archive = cache / f'onecta-{SHA256}.tar.gz'
    if archive.exists() and hashlib.sha256(archive.read_bytes()).hexdigest() != SHA256:
        raise ValueError('Cached Onecta archive checksum mismatch')
    if not archive.exists():
        with urllib.request.urlopen(URL, timeout=45) as response:
            data = response.read(MAX_ARCHIVE_BYTES + 1)
        if len(data) > MAX_ARCHIVE_BYTES or hashlib.sha256(data).hexdigest() != SHA256:
            raise ValueError('Downloaded Onecta archive checksum mismatch')
        partial = archive.with_suffix('.partial')
        partial.write_bytes(data)
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
    install(args.config, args.bootstrap)

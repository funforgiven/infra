"""Make a derived chart cache with hash-pinned, self-contained values schemas."""
import copy
import hashlib
import io
import json
from pathlib import Path
import shutil
import tarfile
from urllib.parse import urldefrag

SOURCE_REF = 'https://raw.githubusercontent.com/yannh/kubernetes-json-schema/master/v1.30.0/_definitions.json'
PINNED = {
    SOURCE_REF: {
        'url': 'https://raw.githubusercontent.com/yannh/kubernetes-json-schema/817113f21a2643311cbc3e992bb44ffe1c416c54/v1.30.0/_definitions.json',
        'sha256': '428559f7d50d8624ce29ea144ba079309a025168e8bb7714e954dcb80d50cd9a',
    },
}


def inline(schema, fetch, pins=PINNED):
    schema = copy.deepcopy(schema)
    external = {}
    sources = {}

    def rewrite(node, prefix=''):
        if isinstance(node, dict):
            # Identifiers affect JSON reference scope. All references in the
            # derived copy are explicitly rewritten against the containing root.
            for key in ('$id', 'id'):
                if isinstance(node.get(key), str):
                    node.pop(key)
            reference = node.get('$ref')
            if isinstance(reference, str):
                if reference.startswith('#'):
                    if prefix:
                        node['$ref'] = prefix + reference[1:]
                else:
                    url, fragment = urldefrag(reference)
                    if url not in pins or (fragment and not fragment.startswith('/')):
                        raise ValueError('unrecognized external chart schema reference')
                    pin = pins[url]
                    name = 'migration_external_' + pin['sha256']
                    anchor = '#/definitions/' + name
                    node['$ref'] = anchor + fragment
                    if name not in external:
                        payload = fetch(pin['url'])
                        if hashlib.sha256(payload).hexdigest() != pin['sha256']:
                            raise ValueError('external chart schema checksum mismatch')
                        document = json.loads(payload)
                        external[name] = document
                        sources[url] = dict(pin, sourceReference=url)
                        rewrite(document, anchor)
            for value in list(node.values()):
                rewrite(value, prefix)
        elif isinstance(node, list):
            for value in node:
                rewrite(value, prefix)

    rewrite(schema)
    definitions = schema.setdefault('definitions', {}) if external else schema.get('definitions', {})
    if set(definitions) & set(external):
        raise ValueError('external schema definition collision')
    definitions.update(external)
    return schema, list(sources.values())


def derived_chart(original, cache, fetch):
    name = hashlib.sha256(str(original.resolve()).encode()).hexdigest() + '.offline-chart'
    derived = cache / name
    if derived.exists():
        shutil.rmtree(derived)
    shutil.copytree(original, derived)

    def expand(directory):
        dependencies = directory / 'charts'
        if not dependencies.exists():
            return
        for archive_path in sorted(dependencies.glob('*.tgz')):
            with tarfile.open(archive_path) as archive:
                archive.extractall(dependencies, filter='data')
            archive_path.unlink()
        for dependency in sorted(dependencies.iterdir()):
            if dependency.is_dir() and (dependency / 'Chart.yaml').is_file():
                expand(dependency)

    expand(derived)
    changes = []
    for path in sorted(derived.rglob('values.schema.json')):
        original_bytes = path.read_bytes()
        schema, sources = inline(json.loads(original_bytes), fetch)
        if sources:
            payload = json.dumps(schema, separators=(',', ':')).encode()
            path.write_bytes(payload)
            changes.append({'file': str(path.relative_to(derived)),
                            'originalSHA256': hashlib.sha256(original_bytes).hexdigest(),
                            'derivedSHA256': hashlib.sha256(payload).hexdigest(),
                            'externalSources': sources})
    return derived, changes

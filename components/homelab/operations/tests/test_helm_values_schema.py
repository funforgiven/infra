import hashlib
import io
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest

import jsonschema

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'validation'))
import helm_values_schema as schemas


class OfflineValuesSchemas(unittest.TestCase):
    def fixture(self):
        remote = {'$id': 'https://example.test/definitions.json', 'definitions': {
            'Leaf': {'type': 'integer'},
            'Object': {'type': 'object', 'properties': {'id': {'type': 'integer'}, '$ref': {'type': 'string'},
                       'value': {'$ref': '#/definitions/Leaf'}}, 'required': ['value']},
        }}
        payload = json.dumps(remote).encode()
        url = 'https://example.test/definitions.json'
        pins = {url: {'url': 'https://example.test/immutable.json',
                      'sha256': hashlib.sha256(payload).hexdigest()}}
        root = {'type': 'object', 'properties': {'native': {'$ref': url + '#/definitions/Object'},
                'local': {'$ref': '#/definitions/Local'}}, 'definitions': {'Local': {'type': 'string'}}}
        return root, payload, pins

    def test_remote_and_local_reference_scopes_preserved(self):
        root, payload, pins = self.fixture()
        original = json.dumps(root)
        derived, sources = schemas.inline(root, lambda url: payload, pins)
        validator = jsonschema.Draft7Validator(derived)
        self.assertEqual(list(validator.iter_errors({'native': {'id': 1, '$ref': 'literal-property', 'value': 2}, 'local': 'ok'})), [])
        self.assertTrue(list(validator.iter_errors({'native': {'value': 'wrong'}, 'local': 'ok'})))
        self.assertTrue(list(validator.iter_errors({'native': {'id': 'wrong', 'value': 2}, 'local': 'ok'})))
        self.assertTrue(list(validator.iter_errors({'native': {'value': 2}, 'local': 42})))
        self.assertEqual(json.dumps(root), original)
        self.assertEqual(sources[0]['url'], pins[next(iter(pins))]['url'])
        self.assertNotIn('"$id"', json.dumps(derived))

    def test_unknown_external_reference_never_fetched(self):
        root, payload, pins = self.fixture()
        root['properties']['native']['$ref'] = 'https://unapproved.test/schema.json'
        def fetch(url):
            self.fail('unapproved source was fetched')
        with self.assertRaises(ValueError):
            schemas.inline(root, fetch, pins)

    def test_external_payload_digest_must_match(self):
        root, payload, pins = self.fixture()
        with self.assertRaises(ValueError):
            schemas.inline(root, lambda url: payload + b' ', pins)

    def test_validation_copy_expands_dependency_without_changing_archive(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            original = directory / 'original'
            dependencies = original / 'charts'
            dependencies.mkdir(parents=True)
            (original / 'Chart.yaml').write_text('apiVersion: v2\nname: fixture\nversion: 1.0.0\n')
            archive_path = dependencies / 'dependency.tgz'
            with tarfile.open(archive_path, 'w:gz') as archive:
                for name, content in [('dependency/Chart.yaml', b'apiVersion: v2\nname: dependency\nversion: 1.0.0\n'),
                                      ('dependency/values.schema.json', b'{"type":"object"}')]:
                    member = tarfile.TarInfo(name)
                    member.size = len(content)
                    archive.addfile(member, io.BytesIO(content))
            before = archive_path.read_bytes()
            cache = directory / 'cache'
            cache.mkdir()
            derived, changes = schemas.derived_chart(original, cache, lambda url: self.fail('unexpected fetch'))
            self.assertEqual(archive_path.read_bytes(), before)
            self.assertFalse((derived / 'charts/dependency.tgz').exists())
            self.assertTrue((derived / 'charts/dependency/values.schema.json').is_file())
            self.assertEqual(changes, [])


if __name__ == '__main__':
    unittest.main()

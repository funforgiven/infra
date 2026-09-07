"""Pinned Forgejo table fixtures and local HTTP; no live DB or credentials."""
import hashlib
import http.client
import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest

spec = importlib.util.spec_from_file_location('descriptors', Path(__file__).parents[1] / 'cache-descriptors.py')
descriptor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(descriptor)


class DescriptorTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.database = self.root / 'forgejo.db'
        self.db = sqlite3.connect(self.database)
        self.addCleanup(self.db.close)
        self.db.executescript('''
            CREATE TABLE repository (id INTEGER PRIMARY KEY, owner_id INTEGER, owner_name TEXT, lower_name TEXT);
            CREATE TABLE action_run (id INTEGER PRIMARY KEY, repo_id INTEGER, owner_id INTEGER, commit_sha TEXT,
                trigger_event TEXT, ref TEXT, status INTEGER, need_approval INTEGER, event_payload TEXT);
            CREATE TABLE action_run_job (id INTEGER PRIMARY KEY, attempt INTEGER, run_id INTEGER, repo_id INTEGER,
                owner_id INTEGER, commit_sha TEXT, name TEXT, runs_on TEXT, job_id TEXT, status INTEGER,
                workflow_payload BLOB, task_id INTEGER);
            INSERT INTO repository VALUES (1,2,'funforgiven','atollion');
        ''')
        self.db.execute('INSERT INTO action_run VALUES (22,1,2,?,?,?,?,0,?)',
                        ('a' * 40, 'pull_request', 'refs/pull/120/head', 5, 'never-return-event-payload'))
        self.db.execute('INSERT INTO action_run_job VALUES (64,2,22,1,2,?,?,?,?,5,?,0)',
                        ('a' * 40, 'linux-quality', '["linux-x86_64"]', 'linux-quality', b'never-return-workflow'))
        self.db.commit()
        self.keys = {}
        for index, platform in enumerate(descriptor.POLICIES):
            key = bytes([ord('a') + index]) * 64
            (self.root / f'cache-{platform}-broker').write_bytes(key)
            self.keys[platform] = key
        self.store = descriptor.Descriptors(self.database, self.root)

    def change(self, sql, args=()):
        self.db.execute(sql, args)
        self.db.commit()

    def test_current_waiting_attempt_metadata_without_task_or_payload(self):
        before = hashlib.sha256(self.database.read_bytes()).hexdigest()
        value = self.store.get(64, 2, 'linux')
        self.assertEqual(value, {'repository': 'funforgiven/atollion', 'job_id': 64, 'attempt': 2, 'run_id': 22,
            'head': 'a' * 40, 'event_name': 'pull_request', 'ref': 'refs/pull/120/head',
            'name': 'linux-quality', 'runs_on': ['linux-x86_64']})
        self.assertEqual(before, hashlib.sha256(self.database.read_bytes()).hexdigest())
        self.change('UPDATE action_run_job SET status=6,task_id=90')
        self.change('UPDATE action_run SET status=6')
        self.assertEqual(self.store.get(64, 2, 'linux'), value)

    def test_stale_future_zero_attempt_and_final_or_blocked_jobs_denied(self):
        for attempt in (0, 1, 3):
            with self.subTest(attempt=attempt), self.assertRaises(descriptor.Refused): self.store.get(64, attempt, 'linux')
        for status in (0, 1, 2, 3, 4, 7):
            self.change('UPDATE action_run_job SET status=?', (status,))
            with self.subTest(status=status), self.assertRaises(descriptor.Refused): self.store.get(64, 2, 'linux')
        self.change('UPDATE action_run_job SET status=5')
        self.change('UPDATE action_run SET need_approval=1')
        with self.assertRaises(descriptor.Refused): self.store.get(64, 2, 'linux')

    def test_wrong_repository_owner_run_commit_and_platform_are_denied(self):
        for sql, undo in (
            ("UPDATE repository SET lower_name='other'", "UPDATE repository SET lower_name='atollion'"),
            ("UPDATE repository SET owner_name='other'", "UPDATE repository SET owner_name='funforgiven'"),
            ('UPDATE repository SET owner_id=99', 'UPDATE repository SET owner_id=2'),
            ("UPDATE action_run_job SET commit_sha='bad'", "UPDATE action_run_job SET commit_sha='" + 'a' * 40 + "'"),
        ):
            self.change(sql)
            with self.subTest(sql=sql), self.assertRaises(descriptor.Refused): self.store.get(64, 2, 'linux')
            self.change(undo)
        with self.assertRaises(descriptor.Refused): self.store.get(64, 2, 'macos')
        self.change('UPDATE action_run_job SET runs_on=?', ('["macos-x86_64"]',))
        with self.assertRaises(descriptor.Refused): self.store.get(64, 2, 'linux')

    def test_no_write_attach_schema_or_payload_read_is_possible(self):
        connection = self.store.connect()
        self.addCleanup(connection.close)
        for sql in ('UPDATE action_run_job SET status=1', 'CREATE TABLE forbidden(x)',
                    "ATTACH DATABASE ':memory:' AS other", 'PRAGMA query_only=OFF',
                    'SELECT workflow_payload FROM action_run_job', 'SELECT event_payload FROM action_run',
                    'SELECT sql FROM sqlite_master'):
            with self.subTest(sql=sql), self.assertRaises(sqlite3.DatabaseError): connection.execute(sql)

    def test_live_wal_changes_are_visible_without_immutable_mode(self):
        self.db.execute('PRAGMA journal_mode=WAL')
        self.change('UPDATE action_run_job SET attempt=3')
        self.assertEqual(self.store.get(64, 3, 'linux')['attempt'], 3)
        with self.assertRaises(descriptor.Refused): self.store.get(64, 2, 'linux')

    def test_actual_http_auth_routes_platform_and_no_payload_output(self):
        server = descriptor.Server(('127.0.0.1', 0), self.store)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        def stop():
            server.shutdown(); server.server_close(); thread.join()
        self.addCleanup(stop)
        def call(path, token, method='GET'):
            client = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=5)
            client.request(method, path, headers={'Authorization': 'Bearer ' + token.decode()})
            response = client.getresponse(); result = response.status, response.read(); client.close(); return result
        self.assertEqual(call('/v1/jobs/64?attempt=2', b'wrong')[0], 403)
        self.assertEqual(call('/v1/jobs/64?attempt=2', self.keys['macos'])[0], 403)
        self.assertEqual(call('/v1/jobs/64?attempt=2', self.keys['linux'], 'POST')[0], 405)
        for route in ('/v1/jobs/64?attempt=2&repo=other', '/v1/jobs/64?attempt=2&attempt=2',
                      '/v1/jobs/64?attempt=0', '/v1/jobs/64?attempt=999', '/v1/jobs/64%20OR%201?attempt=2'):
            self.assertEqual(call(route, self.keys['linux'])[0], 404)
        status, raw = call('/v1/jobs/64?attempt=2', self.keys['linux'])
        self.assertEqual(status, 200)
        self.assertNotIn(b'never-return', raw)
        self.assertEqual(json.loads(raw)['attempt'], 2)


if __name__ == '__main__':
    unittest.main(verbosity=2)

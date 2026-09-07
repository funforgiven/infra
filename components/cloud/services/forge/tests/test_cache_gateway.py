"""Disposable local HTTP fixtures; no actual runner, host or Forgejo calls."""
import hashlib
import hmac
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import io
import sqlite3
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import importlib.util

spec = importlib.util.spec_from_file_location("cache_gateway", Path(__file__).parents[1] / "cache-gateway.py")
gateway = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gateway)


class Backend(BaseHTTPRequestHandler):
    def log_message(self, *_): pass
    def reply(self, value=None, status=200):
        data = b"" if value is None else json.dumps(value).encode()
        self.send_response(status); self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
    def do_POST(self):
        value = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.server.seen.append(dict(self.headers))
        if self.path.endswith("/caches"):
            self.server.next_id += 1; identity = self.server.next_id
            self.server.entries[identity] = {"body": value, "chunks": {}}
            self.reply({"cacheId": identity})
        else:
            identity = int(self.path.rsplit("/", 1)[1]); row = self.server.entries[identity]
            data = b"".join(row["chunks"][i] for i in sorted(row["chunks"]))
            path = self.server.root / f"{identity % 255:02x}" / str(identity)
            path.parent.mkdir(exist_ok=True); path.write_bytes(data); self.reply()
    def do_PATCH(self):
        identity = int(self.path.rsplit("/", 1)[1]); start = int(self.headers["Content-Range"].split()[1].split("-")[0])
        self.server.entries[identity]["chunks"][start] = self.rfile.read(int(self.headers["Content-Length"]))
        self.server.seen.append(dict(self.headers)); self.reply()
    def do_GET(self):
        if "/cache?" in self.path:
            if not self.server.next_id: return self.reply(status=204)
            identity = self.server.next_id
            location = self.headers["Forgejo-Cache-Host"] + "/" + self.headers["Forgejo-Cache-RunId"] + gateway.API + "/artifacts/" + str(identity)
            self.reply({"archiveLocation": self.server.bad_location or location, "cacheKey": "test-key"})
        else:
            identity = int(self.path.rsplit("/", 1)[1]); data = (self.server.root / f"{identity % 255:02x}" / str(identity)).read_bytes()
            self.send_response(200); self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)


class GatewayTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup); self.root = Path(temporary.name)
        (self.root / "cache").mkdir(); (self.root / "secret").write_bytes(b"s" * 64); (self.root / "broker").write_bytes(b"b" * 64)
        self.backend = ThreadingHTTPServer(("127.0.0.1", 0), Backend)
        self.backend.handle_error = lambda *_: None  # Expected aborted-upload fixture disconnect.
        self.backend.root = self.root / "cache"; self.backend.entries = {}; self.backend.next_id = 0
        self.backend.seen = []; self.backend.bad_location = None
        self.backend_thread = threading.Thread(target=self.backend.serve_forever, daemon=True); self.backend_thread.start()
        self.config = {"public_url": "https://cache.example.test", "cache_root": str(self.root / "cache"),
                       "state_path": str(self.root / "gateway.sqlite3"), "backend_secret_file": str(self.root / "secret"),
                       "broker_tokens": {str(self.root / "broker"): {"repositories": ["owner/repo"], "lanes": sorted(gateway.LANES)}},
                       "quota_bytes": 100 * 1024**2, "minimum_free_bytes": 0, "backend_port": self.backend.server_port}
        self.store = gateway.Store(self.config)
        self.server = gateway.Server(("127.0.0.1", 0), self.store, False)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True); self.thread.start()
        self.addCleanup(self.stop)
        self.auth = b"Bearer " + b"b" * 64
        self.request_value = {"repository": "owner/repo", "job_id": 1, "attempt": 1, "run_id": 22, "head": "a" * 40,
                              "event_name": "pull_request", "ref": "refs/pull/120/head", "cache_lane": "linux-quality",
                              "expires_unix": int(time.time()) + 3600}
        self.issued = self.store.issue(self.request_value, self.auth)
        self.cap = self.issued["actions_cache_url"].split("/")[-2]

    def stop(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join()
        self.backend.shutdown(); self.backend.server_close(); self.backend_thread.join(); self.store.db.close()

    def request(self, method, route, value=None, headers=None, cap=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        data = json.dumps(value).encode() if isinstance(value, dict) else value
        connection.request(method, "/" + (cap or self.cap) + gateway.API + route, body=data, headers=headers or {})
        response = connection.getresponse(); result = response.status, response.read(); connection.close(); return result

    def reserve(self, size=6):
        status, raw = self.request("POST", "/caches", {"key": "test-key", "version": "v1", "cacheSize": size})
        self.assertEqual(status, 200, raw); return json.loads(raw)["cacheId"]

    def complete(self, content=b"abcdef"):
        identity = self.reserve(len(content))
        self.assertEqual(self.request("PATCH", f"/caches/{identity}", content,
                         {"Content-Range": f"bytes 0-{len(content)-1}/*"})[0], 200)
        self.assertEqual(self.request("POST", f"/caches/{identity}", {"size": len(content)})[0], 200)
        return identity

    def test_job_attempt_retry_gets_distinct_capability_without_reinterpreting_claims(self):
        self.assertEqual(self.store.issue(self.request_value, self.auth), self.issued)
        retry = self.store.issue({**self.request_value, "attempt": 2}, self.auth)
        self.assertNotEqual(retry["lease_id"], self.issued["lease_id"])
        self.assertNotEqual(retry["actions_cache_url"], self.issued["actions_cache_url"])
        with self.assertRaises(gateway.Refused) as changed:
            self.store.issue({**self.request_value, "head": "b" * 40}, self.auth)
        self.assertEqual(changed.exception.status, 409)
        for invalid in ({"job_id": 0}, {"attempt": 0}, {"attempt": True}):
            with self.subTest(invalid=invalid), self.assertRaises(gateway.Refused):
                self.store.issue({**self.request_value, **invalid}, self.auth)
        legacy = {**self.request_value, "task_id": 1};del legacy["job_id"];del legacy["attempt"]
        with self.assertRaises(gateway.Refused): self.store.issue(legacy, self.auth)
        self.assertEqual(self.store.db.execute("SELECT task,job_id,attempt FROM leases ORDER BY attempt").fetchall(),
                         [(None,1,1),(None,1,2)])

    def test_empty_legacy_database_migrates_but_issued_legacy_leases_refuse(self):
        for issued in (False, True):
            path=self.root/("legacy-issued.sqlite3" if issued else "legacy-empty.sqlite3")
            with sqlite3.connect(path) as db:
                db.execute("CREATE TABLE leases (id TEXT PRIMARY KEY, task INTEGER UNIQUE, value TEXT NOT NULL, capability_hash TEXT UNIQUE NOT NULL)")
                if issued: db.execute("INSERT INTO leases VALUES ('old',1,'{}','old-hash')")
            configuration={**self.config,"state_path":str(path)}
            if issued:
                with self.assertRaises(gateway.Refused): gateway.Store(configuration)
                with sqlite3.connect(path) as db:
                    self.assertEqual(db.execute("SELECT COUNT(*) FROM leases").fetchone()[0],1)
                    self.assertNotIn("job_id",{row[1] for row in db.execute("PRAGMA table_info(leases)")})
            else:
                migrated=gateway.Store(configuration)
                try:
                    self.assertTrue({"task","job_id","attempt"} <= {row[1] for row in migrated.db.execute("PRAGMA table_info(leases)")})
                    self.assertTrue(migrated.issue(self.request_value,self.auth)["lease_id"])
                finally: migrated.db.close()

    def test_real_http_reserve_stream_commit_lookup_and_download(self):
        self.assertEqual(self.request("GET", "/cache?keys=test-key&version=v1")[0], 204)
        content = b"cached-dependency\0" * 150000; identity = self.complete(content)
        status, raw = self.request("GET", "/cache?keys=test-key&version=v1")
        self.assertEqual(status, 200); self.assertEqual(json.loads(raw)["archiveLocation"], self.issued["actions_cache_url"].rstrip("/") + gateway.API + f"/artifacts/{identity}")
        self.assertEqual(self.request("GET", f"/artifacts/{identity}"), (200, content))

    def test_header_injection_never_reaches_backend_or_master_key_response(self):
        status, raw = self.request("POST", "/caches", {"key": "test-key", "version": "v1", "cacheSize": 6},
                                  {"Authorization": "Bearer job-secret", "Cookie": "leak", "Forgejo-Cache-Repo": "foreign", "Forgejo-Cache-WriteIsolationKey": ""})
        self.assertEqual(status, 200); headers = self.backend.seen[-1]
        self.assertNotIn("Authorization", headers); self.assertNotIn("Cookie", headers)
        self.assertEqual(headers["Forgejo-Cache-Repo"], "owner/repo:linux-quality")
        self.assertEqual(headers["Forgejo-Cache-WriteIsolationKey"], "refs/pull/120/head")
        message = ">".join(headers[k] for k in ("Forgejo-Cache-Repo", "Forgejo-Cache-RunNumber", "Forgejo-Cache-Timestamp", "Forgejo-Cache-WriteIsolationKey"))
        self.assertEqual(headers["Forgejo-Cache-MAC"], hmac.new(b"s" * 64, message.encode(), hashlib.sha256).hexdigest())
        self.assertNotIn(b"s" * 64, raw)

    def test_unknown_expired_and_revoked_capability_cannot_reserve(self):
        payload = {"key": "x", "version": "v", "cacheSize": 1}
        self.assertEqual(self.request("POST", "/caches", payload, cap="0" * 64)[0], 403)
        with patch.object(gateway.time, "time", return_value=self.request_value["expires_unix"] + 1):
            self.assertEqual(self.request("POST", "/caches", payload)[0], 403)
        self.store.revoke(self.issued["lease_id"], self.auth)
        self.assertEqual(self.request("POST", "/caches", payload)[0], 403)
        self.assertEqual(self.backend.next_id, 0)

    def test_cross_pr_and_platform_ids_refused_before_backend(self):
        identity = self.complete()
        for change in ({"ref": "refs/pull/121/head"}, {"cache_lane": "macos-native"}):
            value = {**self.request_value, **change, "job_id": self.request_value["job_id"] + 1}
            issued = self.store.issue(value, self.auth); cap = issued["actions_cache_url"].split("/")[-2]
            self.assertEqual(self.request("GET", f"/artifacts/{identity}", cap=cap)[0], 404)
            self.store.revoke(issued["lease_id"], self.auth); self.request_value["job_id"] += 1

    def test_only_protected_main_push_gets_shared_scope_and_pr_can_read_it(self):
        policy = next(iter(self.config["broker_tokens"].values()))
        for event, ref in [("workflow_dispatch", "refs/heads/main"), ("push", "refs/heads/worker")]:
            value = gateway.scope({**self.request_value, "event_name": event, "ref": ref}, policy, int(time.time()))
            self.assertNotEqual(value["isolation"], "")
        value = {**self.request_value, "job_id": 2, "event_name": "push", "ref": "refs/heads/main"}
        issued = self.store.issue(value, self.auth); original = self.cap; self.cap = issued["actions_cache_url"].split("/")[-2]
        identity = self.complete(); self.cap = original
        self.assertEqual(self.request("GET", f"/artifacts/{identity}")[0], 200)
        self.assertEqual(self.request("PATCH", f"/caches/{identity}", b"x", {"Content-Range": "bytes 0-0/*"})[0], 403)

    def test_bad_routes_and_backend_absolute_urls_are_rejected(self):
        for path in ("http://attacker.invalid/path", "//attacker.invalid/path", "/" + self.cap + gateway.API + "/artifacts/%31", "/" + self.cap + gateway.API + "/cache?keys=x&version=v&version=w"):
            with self.assertRaises((gateway.Refused, ValueError)): gateway.request_route("GET", path)
        self.complete(); self.backend.bad_location = "http://attacker.invalid/credential"
        self.assertEqual(self.request("GET", "/cache?keys=test-key&version=v1")[0], 502)

    def test_upload_gaps_overlaps_size_and_quota_rejected(self):
        identity = self.reserve()
        self.assertEqual(self.request("PATCH", f"/caches/{identity}", b"abc", {"Content-Range": "bytes 0-2/*"})[0], 200)
        self.assertEqual(self.request("PATCH", f"/caches/{identity}", b"ab", {"Content-Range": "bytes 2-3/*"})[0], 409)
        self.assertEqual(self.request("POST", f"/caches/{identity}", {"size": 6})[0], 409)
        self.assertEqual(self.request("PATCH", f"/caches/{identity}", b"abc", {"Content-Range": "bytes 3-6/*"})[0], 400)
        self.store.config["quota_bytes"] = 12
        self.assertEqual(self.request("POST", "/caches", {"key": "other", "version": "v", "cacheSize": 1})[0], 507)

    def test_actual_chunked_sendstream_framing_and_pending_range_after_abort(self):
        identity = self.reserve()
        status, _ = self.request("PATCH", f"/caches/{identity}", b"3\r\nabc\r\n0\r\n\r\n",
                                 {"Transfer-Encoding": "chunked", "Content-Range": "bytes 0-5/*"})
        self.assertEqual(status, 400)
        with self.store.lock:
            self.assertEqual(self.store.db.execute("SELECT start,finish,complete FROM chunks WHERE id=?", (identity,)).fetchall(), [(0, 5, 0)])
        self.assertEqual(self.request("PATCH", f"/caches/{identity}", b"bc", {"Content-Range": "bytes 1-2/*"})[0], 409)
        self.assertEqual(self.request("POST", f"/caches/{identity}", {"size": 6})[0], 409)
        self.assertEqual(self.request("PATCH", f"/caches/{identity}", b"3\r\nabc\r\n3\r\ndef\r\n0\r\n\r\n",
                         {"Transfer-Encoding": "chunked", "Content-Range": "bytes 0-5/*"})[0], 200)
        self.assertEqual(self.request("POST", f"/caches/{identity}", {"size": 6})[0], 200)
        self.assertEqual(self.request("GET", f"/artifacts/{identity}"), (200, b"abcdef"))

    def test_chunked_decoder_rejects_oversize_trailers_extensions_and_truncation(self):
        for raw in (b"7\r\nabcdefg\r\n0\r\n\r\n", b"6;extension=x\r\nabcdef\r\n0\r\n\r\n",
                    b"6\r\nabcdef\r\n0\r\nTrailer: x\r\n\r\n", b"6\r\nabc"):
            with self.subTest(raw=raw), self.assertRaises(gateway.Refused):
                list(gateway.upload_chunks(io.BytesIO(raw), 6, "chunked"))

    def test_broker_identity_scope_and_maximum_ttl_reject_forged_requests(self):
        with self.assertRaises(gateway.Refused): self.store.issue(self.request_value, b"Bearer job-token")
        for change in ({"repository": "foreign/repo"}, {"expires_unix": int(time.time()) + 7201},
                       {"head": "not-a-head"}, {"event_name": "pull_request_target"}, {"cache_lane": "foreign"}):
            with self.subTest(change=change), self.assertRaises(gateway.Refused):
                self.store.issue({**self.request_value, **change, "job_id": 2}, self.auth)

    def test_entry_and_range_counts_are_bounded_even_for_tiny_archives(self):
        with patch.object(gateway, "MAX_ACTIVE_ENTRIES_PER_LEASE", 1):
            identity = self.reserve(3)
            self.assertEqual(self.request("POST", "/caches", {"key": "x", "version": "v", "cacheSize": 1})[0], 429)
        with patch.object(gateway, "MAX_RANGES_PER_ENTRY", 1):
            self.assertEqual(self.request("PATCH", f"/caches/{identity}", b"a", {"Content-Range": "bytes 0-0/*"})[0], 200)
            self.assertEqual(self.request("PATCH", f"/caches/{identity}", b"b", {"Content-Range": "bytes 1-1/*"})[0], 429)
        with patch.object(gateway, "MAX_ENTRIES", 1):
            self.assertEqual(self.request("POST", "/caches", {"key": "x", "version": "v", "cacheSize": 1})[0], 507)
        self.assertEqual(self.backend.next_id, 1)

    def test_revoked_or_timed_out_waiter_cannot_mutate_after_lock(self):
        original = self.store.prune
        def revoke_during_preparation(needed):
            original(needed)
            self.store.revoke(self.issued["lease_id"], self.auth)
        with patch.object(self.store, "prune", revoke_during_preparation):
            self.assertEqual(self.request("POST", "/caches", {"key": "x", "version": "v", "cacheSize": 1})[0], 403)
        self.assertEqual(self.backend.next_id, 0)
        handler = object.__new__(gateway.Handler)
        handler.request_deadline = time.monotonic() - 1
        handler.server = self.server
        with self.assertRaises(gateway.Refused) as failure:
            handler.active(self.issued["lease_id"])
        self.assertEqual(failure.exception.status, 408)

    def test_lru_removes_only_known_inactive_cache_files_and_preserves_reader(self):
        identity = self.complete(); outside = self.root / "unrelated"; outside.write_text("preserve")
        with self.store.lock:
            self.store.db.execute("UPDATE entries SET used=? WHERE id=?", (int(time.time()) - 600, identity)); self.store.db.commit()
            self.store.config["quota_bytes"] = 6; self.store.reading[identity] = 1
            with self.assertRaises(gateway.Refused): self.store.prune(6)
            self.assertTrue(self.store.archive(identity).exists()); del self.store.reading[identity]
            self.store.prune(6)
        self.assertFalse(self.store.archive(identity).exists()); self.assertEqual(outside.read_text(), "preserve")


if __name__ == "__main__": unittest.main(verbosity=2)

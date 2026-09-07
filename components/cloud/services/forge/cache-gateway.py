#!/usr/bin/env python3
"""Private cache gateway for trusted brokers and disposable Forgejo jobs.

Only brokers issue scopes derived from authoritative Forgejo run-job/run metadata.
The job receives an expiring opaque URL, never the backend HMAC or broker key.
The patched Forgejo Runner13 cache backend is reachable only on loopback8081.
"""
import argparse
import hashlib
import hmac
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import socket
import sqlite3
import threading
import time
from urllib.parse import parse_qs, urlsplit

MAX_ARCHIVE = 10 * 1024**3
MAX_CHUNK = 32 * 1024**2
MAX_JSON = 16384
MAX_LEASE = 7200
MAX_ENTRIES = 8192
MAX_ACTIVE_ENTRIES_PER_LEASE = 12
MAX_RANGES_PER_ENTRY = 512
MAX_RANGES = 32768
LANES = {"linux-quality", "windows-build", "macos-native", "windows-native"}
API = "/_apis/artifactcache"


class Refused(Exception):
    def __init__(self, status=403):
        self.status = status


def require(ok, status=403):
    if not ok:
        raise Refused(status)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def scope(value, broker, now):
    require(set(value) == {"repository", "job_id", "attempt", "run_id", "head", "event_name", "ref", "cache_lane", "expires_unix"}, 400)
    require(value["repository"] in broker["repositories"] and value["cache_lane"] in broker["lanes"])
    require(all(type(value[k]) is int and value[k] > 0 for k in ("job_id", "attempt", "run_id")), 400)
    require(re.fullmatch(r"[0-9a-f]{40}", value["head"]) is not None, 400)
    require(type(value["expires_unix"]) is int and now < value["expires_unix"] <= now + MAX_LEASE, 400)
    event, ref = value["event_name"], value["ref"]
    if event == "pull_request":
        require(re.fullmatch(r"refs/pull/[1-9][0-9]*/(head|merge)", ref) is not None, 400)
        isolation = ref
    elif event == "push" and ref == "refs/heads/main":
        isolation = ""
    else:
        # Dispatch and worker-branch pushes never acquire shared write rights.
        require(event in {"push", "workflow_dispatch"} and re.fullmatch(r"refs/heads/[A-Za-z0-9_./-]+", ref) is not None, 400)
        isolation = "untrusted:" + ref
    return {**value, "namespace": value["repository"] + ":" + value["cache_lane"], "isolation": isolation}


def request_route(method, target):
    require(len(target) <= 16384 and target.startswith("/") and not target.startswith("//"), 400)
    parsed = urlsplit(target)
    require(not parsed.scheme and not parsed.netloc and not parsed.fragment and "%" not in parsed.path, 400)
    match = re.fullmatch(r"/([0-9a-f]{64})(/_apis/artifactcache/(?:cache|caches|caches/[1-9][0-9]*|artifacts/[1-9][0-9]*|clean))", parsed.path)
    require(match is not None, 404)
    cap, path = match.groups()
    allowed = ((method == "GET" and path == API + "/cache") or
               (method == "POST" and path in {API + "/caches", API + "/clean"}) or
               (method in {"PATCH", "POST"} and re.fullmatch(API + r"/caches/[1-9][0-9]*", path)) or
               (method == "GET" and re.fullmatch(API + r"/artifacts/[1-9][0-9]*", path)))
    require(bool(allowed), 405)
    if path == API + "/cache":
        query = parse_qs(parsed.query, strict_parsing=True)
        require(set(query) == {"keys", "version"} and all(len(v) == 1 for v in query.values()), 400)
        require(0 < len(query["version"][0]) <= 128, 400)
        keys = query["keys"][0].split(",")
        require(0 < len(keys) <= 10 and all(0 < len(k) <= 512 for k in keys), 400)
    else:
        require(not parsed.query, 400)
    return cap, path, parsed.query


def upload_mode(headers, expected):
    transfer = headers.get_all("Transfer-Encoding", [])
    lengths = headers.get_all("Content-Length", [])
    if transfer:
        require(transfer == ["chunked"] and not lengths, 400)
        return "chunked"
    require(len(lengths) == 1 and int(lengths[0]) == expected, 400)
    return "fixed"


def upload_chunks(stream, length, mode):
    """Decode the action's sendStream chunked body within its Content-Range.

    The range sets the hard decoded bound; trailers/extensions and conflicting
    transfer framing are rejected. The caller's request timer bounds slow peers.
    """
    remaining = length
    while remaining or mode == "chunked":
        if mode == "chunked":
            line = stream.readline(128)
            require(re.fullmatch(rb"[0-9A-Fa-f]{1,8}\r\n", line) is not None, 400)
            amount = int(line, 16)
            require(amount <= remaining, 413)
            if amount == 0:
                require(remaining == 0 and stream.read(2) == b"\r\n", 400)
                return
        else:
            amount = remaining
        while amount:
            chunk = stream.read(min(1024**2, amount))
            require(bool(chunk), 400)
            amount -= len(chunk); remaining -= len(chunk)
            yield chunk
        if mode == "chunked":
            require(stream.read(2) == b"\r\n", 400)


class Store:
    def __init__(self, configuration):
        self.config = configuration
        self.public = configuration["public_url"].rstrip("/")
        require(re.fullmatch(r"https://[a-z0-9.-]+", self.public) is not None, 500)
        self.secret = Path(configuration["backend_secret_file"]).read_bytes().strip()
        require(len(self.secret) >= 32, 500)
        self.root = Path(configuration["cache_root"])
        require(self.root.is_dir() and self.root.resolve() == self.root, 500)
        self.lock = threading.RLock()
        self.reading = {}
        self.db = sqlite3.connect(configuration["state_path"], check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
          CREATE TABLE IF NOT EXISTS leases (id TEXT PRIMARY KEY, task INTEGER UNIQUE, value TEXT NOT NULL,
            capability_hash TEXT UNIQUE NOT NULL);
          CREATE TABLE IF NOT EXISTS entries (id INTEGER PRIMARY KEY, namespace TEXT, isolation TEXT,
            size INTEGER, used INTEGER, created INTEGER, complete INTEGER, owner TEXT);
          CREATE TABLE IF NOT EXISTS chunks (id INTEGER, start INTEGER, finish INTEGER, complete INTEGER, PRIMARY KEY(id,start));
        """)
        # The initial deployment used task_id before a task existed in Forgejo.
        # Keep its unused nullable task column, but never reinterpret issued leases.
        columns = {row[1] for row in self.db.execute("PRAGMA table_info(leases)")}
        missing = {"job_id", "attempt"} - columns
        if missing:
            require(self.db.execute("SELECT COUNT(*) FROM leases").fetchone()[0] == 0, 500)
            with self.db:
                for name in sorted(missing):
                    self.db.execute(f"ALTER TABLE leases ADD COLUMN {name} INTEGER")
        self.db.execute("CREATE UNIQUE INDEX IF NOT EXISTS leases_job_attempt ON leases(job_id,attempt)")
        self.db.commit()
        self.brokers = [(Path(path).read_bytes().strip(), policy) for path, policy in configuration["broker_tokens"].items()]
        require(all(len(token) >= 32 and set(policy["lanes"]) <= LANES for token, policy in self.brokers), 500)

    def capability(self, identity):
        return hmac.new(self.secret, b"gateway-lease\x00" + identity.encode(), hashlib.sha256).hexdigest()

    def issue(self, value, authorization):
        matches = [policy for token, policy in self.brokers if hmac.compare_digest(authorization, b"Bearer " + token)]
        require(len(matches) == 1)
        approved = scope(value, matches[0], int(time.time()))
        with self.lock:
            self.db.execute("DELETE FROM leases WHERE CAST(json_extract(value,'$.expires_unix') AS INTEGER) < ?",
                            (int(time.time()) - 86400,))
            previous = self.db.execute("SELECT id,value FROM leases WHERE job_id=? AND attempt=?",
                                       (approved["job_id"], approved["attempt"])).fetchone()
            if previous:
                require(json.loads(previous[1]) == approved, 409)
                identity = previous[0]
            else:
                require(self.db.execute("SELECT COUNT(*) FROM leases").fetchone()[0] < 4096, 503)
                identity = secrets.token_hex(16)
                cap_hash = hashlib.sha256(self.capability(identity).encode()).hexdigest()
                self.db.execute("INSERT INTO leases (id,value,capability_hash,job_id,attempt) VALUES (?,?,?,?,?)",
                                (identity, canonical(approved), cap_hash, approved["job_id"], approved["attempt"]))
            self.db.commit()
        return {"lease_id": identity, "actions_cache_url": self.public + "/" + self.capability(identity) + "/",
                "cache_mode": "broker-scoped-v1", "expires_unix": approved["expires_unix"]}

    def revoke(self, identity, authorization):
        require(re.fullmatch(r"[0-9a-f]{32}", identity) is not None, 400)
        matches = [policy for token, policy in self.brokers if hmac.compare_digest(authorization, b"Bearer " + token)]
        require(len(matches) == 1)
        with self.lock:
            row = self.db.execute("SELECT value FROM leases WHERE id=?", (identity,)).fetchone()
            if row:
                value = json.loads(row[0])
                require(value["repository"] in matches[0]["repositories"] and value["cache_lane"] in matches[0]["lanes"])
                value["expires_unix"] = 0
                self.db.execute("UPDATE leases SET value=? WHERE id=?", (canonical(value), identity))
                self.db.commit()

    def lease(self, cap):
        with self.lock:
            row = self.db.execute("SELECT id,value FROM leases WHERE capability_hash=?",
                                  (hashlib.sha256(cap.encode()).hexdigest(),)).fetchone()
        require(row is not None)
        identity, raw = row
        require(hmac.compare_digest(self.capability(identity), cap))
        value = json.loads(raw)
        require(value["expires_unix"] > time.time())
        return identity, value

    def alive(self, identity):
        with self.lock:
            row = self.db.execute("SELECT value FROM leases WHERE id=?", (identity,)).fetchone()
            require(row is not None and json.loads(row[0])["expires_unix"] > time.time())

    def headers(self, cap, value):
        stamp = str(int(time.time()))
        mac_data = ">".join((value["namespace"], str(value["run_id"]), stamp, value["isolation"]))
        # Construct a new header set: no caller Authorization/Cookie/Forgejo headers survive.
        return {"Forgejo-Cache-Repo": value["namespace"], "Forgejo-Cache-RunNumber": str(value["run_id"]),
                "Forgejo-Cache-Timestamp": stamp, "Forgejo-Cache-WriteIsolationKey": value["isolation"],
                "Forgejo-Cache-MAC": hmac.new(self.secret, mac_data.encode(), hashlib.sha256).hexdigest(),
                "Forgejo-Cache-Host": self.public, "Forgejo-Cache-RunId": cap}

    def archive(self, identity):
        require(type(identity) is int and identity > 0, 400)
        path = self.root / f"{identity % 255:02x}" / str(identity)
        require(path.parent.resolve() == path.parent and not path.is_symlink(), 500)
        return path

    def prune(self, needed=0):
        # Called under the same lock as reserves, commits and chunk writes.
        now = int(time.time())
        for row in self.db.execute("SELECT id,complete,created,used FROM entries").fetchall():
            identity, complete, created, used = row
            if not complete and now - used > 300:
                temporary = self.root / "tmp" / str(identity)
                require(temporary.parent.resolve() == temporary.parent and not temporary.is_symlink(), 500)
                if temporary.exists():
                    shutil.rmtree(temporary)
                self.archive(identity).unlink(missing_ok=True)
                self.db.execute("DELETE FROM chunks WHERE id=?", (identity,))
                self.db.execute("DELETE FROM entries WHERE id=?", (identity,))
            if complete and not self.archive(identity).exists():
                self.db.execute("DELETE FROM entries WHERE id=?", (identity,))
        self.db.commit()
        def charged():
            return self.db.execute("SELECT COALESCE(SUM(size*(CASE complete WHEN 1 THEN 1 ELSE 2 END)),0) FROM entries").fetchone()[0]
        candidates = self.db.execute("SELECT id,created,used FROM entries WHERE complete=1 ORDER BY used,id").fetchall()
        for identity, created, used in candidates:
            space_ok = charged() + needed <= self.config["quota_bytes"] and shutil.disk_usage(self.root).free >= needed + self.config["minimum_free_bytes"]
            expired = now - used > 7 * 86400 or now - created > 30 * 86400
            if space_ok and not expired:
                continue
            if identity in self.reading or now - used < 300:
                continue
            # Only completed archives known to this gateway are removed. Backend
            # find() prunes its stale index when it sees an absent archive.
            self.archive(identity).unlink(missing_ok=True)
            self.db.execute("DELETE FROM entries WHERE id=?", (identity,))
            self.db.execute("DELETE FROM chunks WHERE id=?", (identity,))
            self.db.commit()
        require(charged() + needed <= self.config["quota_bytes"] and
                shutil.disk_usage(self.root).free >= needed + self.config["minimum_free_bytes"], 507)

    def entry(self, identity, lease_id, value, write=False):
        row = self.db.execute("SELECT namespace,isolation,size,complete,owner FROM entries WHERE id=?", (identity,)).fetchone()
        require(row is not None, 404)
        require(row[0] == value["namespace"] and row[1] in ("", value["isolation"]), 404)
        if write:
            require(not row[3] and row[1] == value["isolation"] and row[4] == lease_id)
        else:
            require(row[3] == 1, 404)
        return row


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def setup(self):
        self.request_deadline = time.monotonic() + 119
        super().setup()

    def active(self, lease_id):
        require(time.monotonic() < self.request_deadline, 408)
        self.server.store.alive(lease_id)

    def log_message(self, *_):
        pass  # Capability URLs and headers must never enter access logs.

    def answer(self, status, value=None):
        if getattr(self, "replied", False):
            self.close_connection = True
            return
        self.replied = True
        raw = b"" if value is None else canonical(value).encode()
        self.send_response(status)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Content-Type", "application/json")
        self.send_header("Connection", "close")
        self.end_headers()
        if raw:
            self.wfile.write(raw)
        self.close_connection = True

    def body(self, limit):
        require(not self.headers.get_all("Transfer-Encoding") and len(self.headers.get_all("Content-Length", [])) == 1, 400)
        length = int(self.headers["Content-Length"])
        require(0 <= length <= limit, 413)
        raw = self.rfile.read(length)
        require(len(raw) == length, 400)
        return raw

    def backend(self, method, path, headers, body=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.store.config.get("backend_port", 8081), timeout=30)
        connection.request(method, path, body=body, headers=headers)
        return connection, connection.getresponse()

    def small(self, method, path, headers, body=None):
        connection, response = self.backend(method, path, headers, body)
        try:
            raw = response.read(MAX_JSON + 1)
            require(len(raw) <= MAX_JSON, 502)
            require(200 <= response.status < 300, 503)
            return response.status, json.loads(raw) if raw else None
        finally:
            connection.close()

    def control(self):
        auth = self.headers.get("Authorization", "").encode()
        if self.command == "POST" and self.path == "/v1/leases":
            self.answer(201, self.server.store.issue(json.loads(self.body(MAX_JSON)), auth))
        elif self.command == "DELETE" and self.path.startswith("/v1/leases/"):
            self.server.store.revoke(self.path.removeprefix("/v1/leases/"), auth)
            self.answer(204)
        else:
            raise Refused(404)

    def data(self):
        store = self.server.store
        cap, path, query = request_route(self.command, self.path)
        lease_id, value = store.lease(cap)
        headers = store.headers(cap, value)
        self.active(lease_id)
        if self.command == "GET" and path == API + "/cache":
            status, result = self.small("GET", path + "?" + query, headers)
            if status == 204:
                return self.answer(204)
            # Never relay a backend-supplied host, scheme or arbitrary download URL.
            location = result["archiveLocation"]
            match = re.fullmatch(re.escape(store.public + "/" + cap + API + "/artifacts/") + r"([1-9][0-9]*)", location)
            require(match is not None, 502)
            with store.lock:
                self.active(lease_id)
                store.entry(int(match[1]), lease_id, value)
            return self.answer(200, {"archiveLocation": location, "cacheKey": result["cacheKey"], "result": "hit"})
        if path == API + "/clean":
            return self.answer(200)  # Jobs cannot choose entries to delete.
        if self.command == "POST" and path == API + "/caches":
            body = json.loads(self.body(MAX_JSON))
            require(set(body) == {"key", "version", "cacheSize"} and type(body["cacheSize"]) is int
                    and 0 < body["cacheSize"] <= MAX_ARCHIVE and 0 < len(body["key"]) <= 512
                    and 0 < len(body["version"]) <= 128, 400)
            with store.lock:
                self.active(lease_id)
                store.prune(2 * body["cacheSize"])
                require(store.db.execute("SELECT COUNT(*) FROM entries").fetchone()[0] < MAX_ENTRIES, 507)
                require(store.db.execute("SELECT COUNT(*) FROM entries WHERE owner=? AND complete=0", (lease_id,)).fetchone()[0]
                        < MAX_ACTIVE_ENTRIES_PER_LEASE, 429)
                self.active(lease_id)
                _, result = self.small("POST", path, headers, canonical(body).encode())
                identity = result["cacheId"]
                require(type(identity) is int and identity > 0, 502)
                now = int(time.time())
                store.db.execute("INSERT INTO entries VALUES (?,?,?,?,?,?,?,?)", (identity, value["namespace"], value["isolation"], body["cacheSize"], now, now, 0, lease_id))
                store.db.commit()
            return self.answer(200, {"cacheId": identity})
        identity = int(path.rsplit("/", 1)[1])
        if self.command == "GET":
            with store.lock:
                self.active(lease_id)
                row = store.entry(identity, lease_id, value)
                store.reading[identity] = store.reading.get(identity, 0) + 1
                store.db.execute("UPDATE entries SET used=? WHERE id=?", (int(time.time()), identity)); store.db.commit()
            try:
                request_range = self.headers.get("Range")
                if request_range:
                    match = re.fullmatch(r"bytes=([0-9]+)-([0-9]*)", request_range)
                    require(match is not None and int(match[1]) < row[2]
                            and (not match[2] or int(match[1]) <= int(match[2]) < row[2]), 416)
                    headers["Range"] = request_range
                connection, response = self.backend("GET", path, headers)
                try:
                    require(response.status in (200, 206), 503)
                    size = int(response.getheader("Content-Length", "-1"))
                    require(0 <= size <= row[2], 502)
                    self.replied = True
                    self.send_response(response.status)
                    for name in ("Content-Length", "Content-Range", "Accept-Ranges"):
                        if response.getheader(name): self.send_header(name, response.getheader(name))
                    self.send_header("Connection", "close"); self.end_headers(); self.close_connection = True
                    remaining = size
                    while remaining:
                        self.active(lease_id)
                        chunk = response.read(min(1024**2, remaining)); require(bool(chunk), 502)
                        self.wfile.write(chunk); remaining -= len(chunk)
                finally:
                    connection.close()
            finally:
                with store.lock:
                    store.reading[identity] -= 1
                    if not store.reading[identity]: del store.reading[identity]
            return
        with store.lock:
            self.active(lease_id)
            row = store.entry(identity, lease_id, value, write=True)
            if self.command == "PATCH":
                match = re.fullmatch(r"bytes ([0-9]+)-([0-9]+)/\*", self.headers.get("Content-Range", ""))
                require(match is not None, 400)
                start, finish = map(int, match.groups())
                length = finish - start + 1
                require(0 < length <= MAX_CHUNK and 0 <= start <= finish < row[2], 400)
                mode = upload_mode(self.headers, length)
                chunks = store.db.execute("SELECT start,finish FROM chunks WHERE id=?", (identity,)).fetchall()
                require(all((start, finish) == part or finish < part[0] or start > part[1] for part in chunks), 409)
                if (start, finish) not in chunks:
                    require(len(chunks) < MAX_RANGES_PER_ENTRY and
                            store.db.execute("SELECT COUNT(*) FROM chunks").fetchone()[0] < MAX_RANGES, 429)
                self.active(lease_id)
                # Reserve the full range before any backend bytes can exist.
                # An aborted upload remains pending and counted; only an exact
                # retry may replace it, so partial files cannot multiply via overlaps.
                store.db.execute("INSERT OR REPLACE INTO chunks VALUES (?,?,?,0)", (identity, start, finish))
                store.db.execute("UPDATE entries SET used=? WHERE id=?", (int(time.time()), identity)); store.db.commit()
                headers.update({"Content-Range": self.headers["Content-Range"], "Content-Length": str(length)})
                connection = http.client.HTTPConnection("127.0.0.1", store.config.get("backend_port", 8081), timeout=30)
                try:
                    connection.putrequest("PATCH", path)
                    for key, content in headers.items(): connection.putheader(key, content)
                    connection.endheaders()
                    for chunk in upload_chunks(self.rfile, length, mode):
                        self.active(lease_id)
                        connection.send(chunk)
                    response = connection.getresponse(); response.read(MAX_JSON + 1)
                    require(200 <= response.status < 300, 503)
                finally:
                    connection.close()
                store.db.execute("UPDATE chunks SET complete=1 WHERE id=? AND start=?", (identity, start))
                store.db.execute("UPDATE entries SET used=? WHERE id=?", (int(time.time()), identity)); store.db.commit()
            else:
                body = json.loads(self.body(MAX_JSON))
                require(body == {"size": row[2]}, 400)
                position = 0
                for start, finish, complete in store.db.execute("SELECT start,finish,complete FROM chunks WHERE id=? ORDER BY start", (identity,)):
                    require(complete == 1, 409)
                    require(start == position, 409); position = finish + 1
                require(position == row[2], 409)
                self.active(lease_id)
                self.small("POST", path, headers, canonical(body).encode())
                require(store.archive(identity).stat().st_size == row[2], 502)
                store.db.execute("UPDATE entries SET complete=1,used=? WHERE id=?", (int(time.time()), identity))
                store.db.execute("DELETE FROM chunks WHERE id=?", (identity,)); store.db.commit()
        self.answer(200)

    def dispatch(self):
        self.replied = False
        try:
            if self.command == "GET" and self.path == "/healthz":
                return self.answer(200, {"status": "ready"})
            if self.server.control:
                self.control()
            else:
                self.data()
        except Refused as error:
            self.answer(error.status)
        except (OSError, ValueError, KeyError, TypeError, sqlite3.Error, http.client.HTTPException):
            self.answer(503)  # Cache service failure never certifies or skips a build.
    do_GET = do_POST = do_PATCH = do_DELETE = dispatch


class Server(ThreadingHTTPServer):
    daemon_threads = True
    def __init__(self, address, store, control):
        super().__init__(address, Handler)
        self.store, self.control = store, control
        self.slots = threading.BoundedSemaphore(8 if control else 32)

    def process_request(self, request, address):
        if not self.slots.acquire(blocking=False):
            request.close()
            return
        try:
            super().process_request(request, address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request, address):
        # Bound headers as well as bodies: a slow header sender must not occupy
        # a slot forever before Handler.dispatch starts.
        request.settimeout(30)
        def close_request():
            try: request.shutdown(socket.SHUT_RDWR)
            except OSError: pass
        deadline = threading.Timer(120, close_request)
        deadline.daemon = True
        deadline.start()
        try:
            super().process_request_thread(request, address)
        finally:
            deadline.cancel()
            self.slots.release()

    def handle_error(self, *_):
        pass  # Do not print request objects, capability URLs or broker headers.


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    store = Store(json.loads(args.config.read_text()))
    servers = []
    for port, control in ((8080, False), (8082, True)):
        server = Server(("0.0.0.0", port), store, control)
        servers.append(server)
    threading.Thread(target=servers[1].serve_forever, daemon=True).start()
    servers[0].serve_forever()


if __name__ == "__main__":
    main()

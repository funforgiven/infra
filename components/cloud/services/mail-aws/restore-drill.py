#!/usr/bin/env python3
"""Rehearse a downloaded Vandelay mailbox archive in a network-isolated Stalwart.

Run only in a private network namespace. Arguments: ARCHIVE STALWART_BINARY.
The target uses temporary SQLite storage, never the production RDS/S3 stores.
No message content or credentials are logged; output contains counts only.
"""

import json
import collections
import hashlib
import os
from pathlib import Path
import secrets
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time

if len(sys.argv) != 3:
    raise SystemExit("Usage: mail-restore-drill ARCHIVE STALWART_BINARY")
archive = Path(sys.argv[1]).resolve(strict=True)
stalwart = str(Path(sys.argv[2]).resolve(strict=True))
os.umask(0o077)
# Refuse to run the restored server in a namespace with external routing.
if (os.stat('/proc/self/ns/net').st_ino == os.stat('/proc/1/ns/net').st_ino
        or len(Path('/proc/net/route').read_text().splitlines()) > 1):
    raise SystemExit('Restore drill requires an isolated network namespace.')
# The drill creates a server database plus a second portable archive. Leave
# space for SQLite journals and the running mail service throughout the test.
if shutil.disk_usage('/var/lib/mail-operations').free < 3 * archive.stat().st_size + 5 * 1024 ** 3:
    raise SystemExit('Insufficient free space for an isolated mailbox restore.')
started = time.monotonic()
with tempfile.TemporaryDirectory(prefix='mail-drill-', dir='/var/lib/mail-operations') as directory:
    work = Path(directory)
    env = {key: value for key, value in os.environ.items() if not key.startswith(('AWS_', 'STALWART_', 'RESTIC_', 'VANDELAY_'))}
    password = secrets.token_hex(32)
    env.update(STALWART_RECOVERY_ADMIN='recovery:' + password, STALWART_RECOVERY_MODE='true',
               STALWART_URL='http://127.0.0.1:8080', STALWART_USER='recovery',
               STALWART_PASSWORD=password, VANDELAY_PASSWORD=password,
               XDG_CACHE_HOME=str(work / 'cache'))
    config = work / 'config.json'
    def run(command, stdin=None):
        result = subprocess.run(command, input=stdin, env=env, text=True, capture_output=True, timeout=600)
        if result.returncode:
            raise RuntimeError(f'{Path(command[0]).name} failed with exit {result.returncode}')
        return result.stdout
    def apply(plans):
        run(['stalwart-cli', 'apply', '--stdin', '--json', '--quiet'], '\n'.join(json.dumps(p) for p in plans))
    def start():
        proc = subprocess.Popen([stalwart, '--config', str(config)], env=env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(60):
            if proc.poll() is not None: raise RuntimeError('Isolated server stopped')
            try:
                with socket.create_connection(('127.0.0.1', 8080), timeout=1): return proc
            except OSError: time.sleep(1)
        proc.terminate(); proc.wait(timeout=20)
        raise RuntimeError('Isolated server did not start')
    proc = start()
    try:
        apply([{'@type':'update','object':'Bootstrap','value':{
            'serverHostname':'restore.fahrican.com','defaultDomain':'fahrican.com',
            'requestTlsCertificate':False,'generateDkimKeys':False,
            'dataStore':{'@type':'Sqlite','path':str(work/'data.sqlite')},
            'blobStore':{'@type':'Default'},'searchStore':{'@type':'Default'},
            'inMemoryStore':{'@type':'Default'},'directory':{'@type':'Internal'},
            'tracer':{'@type':'Stdout','level':'error'},'dnsServer':{'@type':'Manual'}}}])
    finally:
        proc.terminate(); proc.wait(timeout=20)
    proc = start()
    try:
        apply([
            {'@type':'upsert','object':'Domain','matchOn':['name'],'value':{'domain':{'name':'fahrican.com','isEnabled':True}}},
            {'@type':'upsert','object':'Account','matchOn':['name'],'value':{'owner':{
                '@type':'User','name':'fahrican','domainId':'#domain','roles':{'@type':'User'},
                'credentials':{'0':{'@type':'Password','secret':password}}}}}])
        apply([{'@type':'reconcile','object':'NetworkListener','matchOn':['name'],'value':{'http':{'name':'http','protocol':'http','bind':{'[::]:8080':True},'useTls':False,'tlsImplicit':False}}}])
        proc.terminate(); proc.wait(timeout=20)
        env.pop('STALWART_RECOVERY_MODE', None)
        env['STALWART_PUBLIC_URL'] = 'http://127.0.0.1:8080'
        proc = start()
        run(['vandelay','export','--url','http://127.0.0.1:8080','--auth-basic','fahrican@fahrican.com','--account-name','fahrican@fahrican.com',str(archive)])
        roundtrip=work/'roundtrip.sqlite'
        run(['vandelay','import','jmap','--url','http://127.0.0.1:8080','--auth-basic','fahrican@fahrican.com','--account-name','fahrican@fahrican.com',str(roundtrip)])
        results = []
        for path in (archive, roundtrip):
            with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as db:
                if db.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                    raise RuntimeError("Restored archive integrity failed")
                blobs = collections.Counter((h, hashlib.sha256(data).digest())
                    for h, data in db.execute("SELECT hash,data FROM blobs"))
                mailbox_rows = {row[0]: row[1:] for row in db.execute(
                    "SELECT id,name,parent_id,role,is_subscribed FROM mailboxes")}
                def mailbox_path(mailbox_id, visited=()):
                    if mailbox_id in visited:
                        raise RuntimeError("Cyclic mailbox hierarchy")
                    name, parent, _, _ = mailbox_rows[mailbox_id]
                    return (*mailbox_path(parent, (*visited, mailbox_id)), name) if parent else (name,)
                emails = collections.Counter((h, received, keywords,
                    tuple(sorted(mailbox_path(int(mid)) for mid in json.loads(mailboxes))))
                    for h, received, keywords, mailboxes in db.execute(
                        "SELECT b.hash,e.received_at,e.keywords,e.mailbox_ids FROM emails e JOIN blobs b ON b.id=e.blob_id"))
                folders = collections.Counter((mailbox_path(mid), row[2], row[3])
                    for mid, row in mailbox_rows.items())
                results.append((blobs, emails, folders))
        if results[0] != results[1]:
            raise RuntimeError("Restored message bytes, dates, flags, or folders differ")
        print(json.dumps({"verified": True, "messages": sum(results[0][1].values()),
            "blobs": sum(results[0][0].values()), "folders": sum(results[0][2].values())}))
        print('Isolated mailbox import/export completed in', round(time.monotonic()-started), 'seconds')
    finally:
        proc.terminate(); proc.wait(timeout=20)

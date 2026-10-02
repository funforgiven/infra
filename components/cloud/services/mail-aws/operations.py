#!/usr/bin/env python3
"""Mail health checks and encrypted portable backups; never log credentials or mail."""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import email
from email import policy
import fcntl
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import smtplib
import socket
import sqlite3
import ssl
import subprocess
import tempfile
import time
import urllib.request
from urllib.parse import quote, urlsplit

HOST = "mail.fahrican.com"
DOMAIN = "fahrican.com"
CANARY = "mail-canary@fahrican.com"
STATE = Path("/var/lib/mail-operations")
SECRETS = Path("/run/stalwart-secrets")
REGION = "eu-central-1"
REPOSITORY = "s3:https://s3.us-west-004.backblazeb2.com/fahrican-cloud-recovery/services/hosts/mail-aws"
ATTACHMENT = b"Stalwart readiness attachment v1\n"
JMAP_CORE = "urn:ietf:params:jmap:core"
JMAP_MAIL = "urn:ietf:params:jmap:mail"
JMAP_SUBMISSION = "urn:ietf:params:jmap:submission"


class OperationError(RuntimeError):
    """Only fixed, non-sensitive diagnostics may cross the logging boundary."""


def jmap_url(url):
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or parsed.hostname != HOST or parsed.port not in (None, 443)
            or parsed.username is not None or parsed.password is not None or parsed.fragment):
        raise OperationError("JMAP endpoint must use the public HTTPS origin")
    return url


class JmapRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        # Discovery redirects are expected; never forward credentials to another
        # origin or permit a TLS downgrade, including on blob downloads.
        return super().redirect_request(request, response, code, message, headers, jmap_url(new_url))


class JmapClient:
    def __init__(self, username, password):
        self.authorization = "Basic " + base64.b64encode(f"{username}:{password}".encode()).decode()
        self.opener = urllib.request.build_opener(JmapRedirect())
        self.session = json.loads(self.request(f"https://{HOST}/.well-known/jmap"))
        self.account = self.session.get("primaryAccounts", {}).get(JMAP_MAIL)
        account = self.session.get("accounts", {}).get(self.account, {})
        if (not self.account or account.get("isReadOnly", True)
                or not {JMAP_CORE, JMAP_MAIL, JMAP_SUBMISSION} <= self.session.get("capabilities", {}).keys()
                or not {JMAP_MAIL, JMAP_SUBMISSION} <= account.get("accountCapabilities", {}).keys()):
            raise OperationError("JMAP mail and submission capabilities unavailable")
        for key in ("apiUrl", "downloadUrl", "uploadUrl", "eventSourceUrl"):
            jmap_url(self.session[key])

    def request(self, url, data=None, content_type="application/json"):
        request = urllib.request.Request(jmap_url(url), data=data, headers={
            "Authorization": self.authorization, "Content-Type": content_type,
            "User-Agent": "fahrican-mail-readiness/1"})
        with self.opener.open(request, timeout=20) as response:
            if response.status not in (200, 201):
                raise OperationError("JMAP HTTP request failed")
            result = response.read(1024 * 1024 + 1)
        if len(result) > 1024 * 1024:
            raise OperationError("JMAP probe response exceeded size limit")
        return result

    def call(self, method, arguments):
        payload = {"using": [JMAP_CORE, JMAP_MAIL, JMAP_SUBMISSION],
                   "methodCalls": [[method, {"accountId": self.account, **arguments}, "probe"]]}
        response = json.loads(self.request(self.session["apiUrl"], json.dumps(payload).encode()))
        for name, result, call_id in response.get("methodResponses", []):
            if call_id == "probe" and name == method and result.get("accountId") == self.account:
                return result
        raise OperationError("JMAP method failed")

    def download(self, blob_id):
        url = self.session["downloadUrl"]
        for key, value in {"accountId": self.account, "blobId": blob_id,
                           "name": "readiness.eml", "type": "message/rfc822"}.items():
            url = url.replace("{" + key + "}", quote(value, safe=""))
        return self.request(url)


def client(service):
    import boto3
    from botocore.config import Config

    return boto3.client(service, region_name=REGION, config=Config(
        connect_timeout=10, read_timeout=30, retries={"max_attempts": 3}))


def run(command, *, env=None, stdin=None, timeout=120):
    try:
        result = subprocess.run(command, input=stdin, env=env, capture_output=True,
                                text=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise OperationError(f"{Path(command[0]).name} could not complete") from error
    if result.returncode:
        # Native tools may echo credentials, account data or API responses.
        raise OperationError(f"{Path(command[0]).name} failed (exit {result.returncode})")
    return result.stdout


def cli(arguments, stdin=None):
    env = os.environ.copy()
    env.update(STALWART_URL=f"https://{HOST}", STALWART_USER=f"admin@{DOMAIN}",
               STALWART_PASSWORD=(SECRETS / "admin-password").read_text().strip())
    return run(["stalwart-cli", *arguments], env=env, stdin=stdin)


def objects(kind, fields):
    return [json.loads(line) for line in cli([
        "query", kind, "--fields", fields, "--json"]).splitlines() if line.strip()]


def reconcile():
    sm = client("secretsmanager")
    try:
        password = secret("canary")
    except sm.exceptions.ResourceNotFoundException:
        password = secrets.token_hex(32)
        # Persist first: retries and replacement instances must use the same
        # credential even if account creation was interrupted.
        sm.put_secret_value(SecretId="fahrican/stalwart/canary", SecretString=password)
    domains = objects("Domain", "id,name")
    domain_id = next(d["id"] for d in domains if d["name"] == DOMAIN)
    accounts = objects("Account", "id,name,aliases")
    owner = next(a for a in accounts if a["name"] == "fahrican")
    aliases = dict(owner.get("aliases", {}))
    for name in ("postmaster", "abuse", "dmarc", "tls-reports"):
        if not any(a.get("name") == name and a.get("domainId") == domain_id for a in aliases.values()):
            index = 0
            while str(index) in aliases:
                index += 1
            aliases[str(index)] = {"enabled": True, "name": name, "domainId": domain_id}
    plans = [
        {"@type": "upsert", "object": "Account", "matchOn": ["name"], "value": {
            "canary": {"@type": "User", "name": "mail-canary", "domainId": domain_id,
                       "description": "Dedicated synthetic delivery checks", "roles": {"@type": "User"},
                       "quotas": {"maxDiskQuota": 104857600},
                       "credentials": {"0": {"@type": "Password", "secret": password}}}}},
        {"@type": "update", "object": "Account", "id": owner["id"], "value": {"aliases": aliases}},
        {"@type": "update", "object": "MtaStageAuth", "value": {"saslMechanisms": {
            "match": {}, "else": "false"}}},
        {"@type": "reconcile", "object": "NetworkListener", "matchOn": ["name"], "value": {
            "smtp": {"name": "smtp", "protocol": "smtp", "bind": {"[::]:25": True},
                     "useTls": True, "tlsImplicit": False},
            "https": {"name": "https", "protocol": "http", "bind": {"[::]:443": True},
                      "useTls": True, "tlsImplicit": True}}},
        {"@type": "update", "object": "Http", "value": {"enableHsts": True}},
        {"@type": "update", "object": "Domain", "id": domain_id,
         "value": {"reportAddressUri": "mailto:tls-reports@fahrican.com"}},
        {"@type": "update", "object": "MtaSts", "value": {
            "mode": "enforce", "maxAge": 604800000, "mxHosts": {HOST: True}}},
    ]
    cli(["apply", "--stdin", "--json", "--quiet"], "\n".join(json.dumps(p) for p in plans))


def write_state(name, document):
    STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", dir=STATE, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            json.dump(document, stream)
            stream.flush()
            os.fsync(stream.fileno())
            os.replace(temporary, STATE / name)
        finally:
            temporary.unlink(missing_ok=True)


def age(name, now=None):
    try:
        timestamp = json.loads((STATE / name).read_text())["last_success"]
        if not isinstance(timestamp, (float, int)) or timestamp <= 0:
            raise ValueError("invalid timestamp")
        return max(0, (time.time() if now is None else now) - timestamp)
    except (OSError, ValueError, KeyError, TypeError):
        # A replaced root volume must prove a new successful operation.
        return 365 * 86400


def metrics(values):
    client("cloudwatch").put_metric_data(Namespace="Fahrican/Mail", MetricData=[
        {"MetricName": key, "Dimensions": [{"Name": "Service", "Value": "stalwart-mail"}],
         "Value": float(value)} for key, value in values.items()])


def secret(name):
    return client("secretsmanager").get_secret_value(
        SecretId=f"fahrican/stalwart/{name}")["SecretString"].strip()


def queue_health(messages, now=None):
    now = time.time() if now is None else now
    timestamps = [dt.datetime.fromisoformat(m["createdAt"].replace("Z", "+00:00")).timestamp()
                  for m in messages]
    return len(messages), max([0, *(now - value for value in timestamps)])


def health():
    values = {"ServiceHealthy": 0, "InboundAgeSeconds": age("canary.json"),
              "BackupAgeSeconds": age("backup.json"), "RestoreAgeSeconds": age("restore.json"),
              "RootFreeBytes": shutil.disk_usage(STATE).free}
    try:
        run(["systemctl", "is-active", "--quiet", "stalwart.service"])
        with socket.create_connection((HOST, 443), timeout=15) as raw:
            with ssl.create_default_context().wrap_socket(raw, server_hostname=HOST) as connection:
                values["CertificateSecondsRemaining"] = ssl.cert_time_to_seconds(
                    connection.getpeercert()["notAfter"]) - time.time()
        jmap = JmapClient(CANARY, secret("canary"))
        folders = jmap.call("Mailbox/get", {"properties": ["id", "role"]})["list"]
        if not any(folder.get("role") == "inbox" for folder in folders):
            raise OperationError("JMAP inbox unavailable")
        if not jmap.call("Identity/get", {"properties": ["id"]})["list"]:
            raise OperationError("JMAP sending identity unavailable")
        # Local SMTP proves the listener speaks SMTP and presents the right
        # certificate. The Resend canary separately proves the public MX path.
        with smtplib.SMTP("127.0.0.1", 25, timeout=15) as smtp:
            smtp.ehlo(HOST)
            smtp._host = HOST
            smtp.starttls(context=ssl.create_default_context())
            if smtp.ehlo(HOST)[0] != 250:
                raise OperationError("SMTP greeting failed")
        count, oldest = queue_health(objects("QueuedMessage", "id,createdAt"))
        values.update(QueueMessages=count, OldestQueuedSeconds=oldest, ServiceHealthy=1)
    finally:
        metrics(values)


def verify_canary(raw, token):
    message = email.message_from_bytes(raw, policy=policy.default)
    if message.get("X-Infra-Probe") != token:
        raise OperationError("Canary identity mismatch")
    if token not in str(message.get("Subject", "")):
        raise OperationError("Canary subject mismatch")
    attachments = [part.get_payload(decode=True) for part in message.iter_attachments()]
    if ATTACHMENT not in attachments:
        raise OperationError("Canary attachment mismatch")


def receive_canary(jmap, token):
    ids = jmap.call("Email/query", {"filter": {"subject": token}, "limit": 20})["ids"]
    if not ids:
        return False
    folders = jmap.call("Mailbox/get", {"properties": ["id", "role"]})["list"]
    inbox = {folder["id"] for folder in folders if folder.get("role") == "inbox"}
    junk = {folder["id"] for folder in folders if folder.get("role") == "junk"}
    messages = jmap.call("Email/get", {"ids": ids, "properties": ["id", "blobId", "mailboxIds"]})
    if messages.get("notFound") or {message["id"] for message in messages["list"]} != set(ids):
        raise OperationError("JMAP canary retrieval incomplete")
    for message in messages["list"]:
        verify_canary(jmap.download(message["blobId"]), token)
        # Only delete a message after its complete MIME identity and attachment
        # have been verified; never clear other mail in the synthetic account.
        result = jmap.call("Email/set", {"destroy": [message["id"]]})
        if message["id"] not in (result.get("destroyed") or []):
            raise OperationError("JMAP canary cleanup failed")
        memberships = {key for key, value in message["mailboxIds"].items() if value}
        if memberships & junk:
            raise OperationError("Canary was classified as junk")
        if not memberships & inbox:
            raise OperationError("Canary did not reach the inbox")
    return True


def canary():
    token = "mail-readiness-" + secrets.token_hex(16)
    payload = {"from": f"Mail readiness <mail-canary@{DOMAIN}>", "to": [CANARY],
               "subject": token, "text": f"Synthetic mail delivery check. {token}",
               "headers": {"X-Infra-Probe": token}, "attachments": [
                   {"filename": "readiness.txt", "content": base64.b64encode(ATTACHMENT).decode()}]}
    request = urllib.request.Request("https://api.resend.com/emails", method="POST",
        data=json.dumps(payload).encode(), headers={"Content-Type": "application/json",
        "User-Agent": "fahrican-mail-readiness/1", "Idempotency-Key": token,
        "Authorization": "Bearer " + (SECRETS / "resend-password").read_text().strip()})
    with urllib.request.urlopen(request, timeout=30) as response:
        if response.status not in (200, 201) or not json.load(response).get("id"):
            raise OperationError("Canary submission failed")
    jmap = JmapClient(CANARY, secret("canary"))
    deadline = time.monotonic() + 240
    while time.monotonic() < deadline:
        if receive_canary(jmap, token):
            write_state("canary.json", {"last_success": time.time()})
            metrics({"InboundAgeSeconds": 0})
            return
        time.sleep(10)
    raise OperationError("Canary did not arrive within four minutes")


def backup_environment():
    bundle = json.loads(secret("backup"))
    env = os.environ.copy()
    env.update(AWS_ACCESS_KEY_ID=bundle["MAIL_AWS_BACKUP_B2_APPLICATION_KEY_ID"],
               AWS_SECRET_ACCESS_KEY=bundle["MAIL_AWS_BACKUP_B2_APPLICATION_KEY"],
               AWS_DEFAULT_REGION="us-west-004", AWS_REGION="us-west-004",
               RESTIC_PASSWORD=bundle["MAIL_AWS_BACKUP_RESTIC_PASSWORD"],
               RESTIC_REPOSITORY=REPOSITORY,
               RESTIC_CACHE_DIR=str(STATE / "restic-cache"))
    env.pop("AWS_SESSION_TOKEN", None)
    return env


def validate_archive(path):
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as connection:
        if connection.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise OperationError("Mailbox archive integrity check failed")


def backup():
    payload = STATE / "payload"
    payload.mkdir(mode=0o700, parents=True, exist_ok=True)
    if shutil.disk_usage(STATE).free < 5 * 1024 ** 3:
        raise OperationError("Insufficient free space for mailbox backup")
    env = os.environ.copy()
    env["VANDELAY_PASSWORD"] = (SECRETS / "mailbox-password").read_text().strip()
    archive = payload / "fahrican.sqlite"
    run(["vandelay", "import", "jmap", "--url", f"https://{HOST}", "--auth-basic",
         f"fahrican@{DOMAIN}", "--account-name", f"fahrican@{DOMAIN}", str(archive)], env=env, timeout=3600)
    validate_archive(archive)
    # The portable account archive is the independent recovery source. A
    # PostgreSQL dump additionally preserves the full server registry/metadata
    # for AWS recovery with matching S3 versions.
    db_env = os.environ.copy()
    db_env.update(PGHOST=os.environ["STALWART_RDS_HOST"], PGDATABASE="stalwart", PGUSER="stalwart",
                  PGPASSWORD=(SECRETS / "rds-password").read_text().strip(), PGSSLMODE="verify-full")
    run(["pg_dump", "--format=custom", "--no-owner", "--no-acl", "--file",
         str(payload / "database.dump")], env=db_env, timeout=1800)
    run(["pg_restore", "--list", str(payload / "database.dump")])
    files = {}
    for path in (archive, payload / "database.dump"):
        with path.open("rb") as stream:
            files[path.name] = hashlib.file_digest(stream, "sha256").hexdigest()
    manifest = {"format": 1, "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                "mailbox": f"fahrican@{DOMAIN}", "files": files}
    (payload / "manifest.json").write_text(json.dumps(manifest, indent=2))
    restic_env = backup_environment()
    # Initialization is a separate operator action; an inaccessible or missing
    # repository must fail instead of silently creating a different backup set.
    run(["restic", "backup", "--quiet", "--tag", "mail-aws", "--host", "mail-aws",
         str(payload)], env=restic_env, timeout=3600)
    write_state("backup.json", {"last_success": time.time()})
    metrics({"BackupAgeSeconds": 0})
    run(["restic", "forget", "--quiet", "--tag", "mail-aws", "--host", "mail-aws",
         "--keep-daily", "14", "--keep-weekly", "8", "--keep-monthly", "12"],
        env=restic_env, timeout=300)


def verify_payload(payload):
    manifest = json.loads((payload / "manifest.json").read_text())
    if manifest.get("format") != 1 or set(manifest["files"]) != {"fahrican.sqlite", "database.dump"}:
        raise OperationError("Unexpected recovery manifest")
    for name, digest in manifest["files"].items():
        with (payload / name).open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != digest:
                raise OperationError("Restored backup checksum mismatch")
    validate_archive(payload / "fahrican.sqlite")
    run(["pg_restore", "--list", str(payload / "database.dump")])


def restore_check():
    env = backup_environment()
    with tempfile.TemporaryDirectory(dir=STATE, prefix="restore-") as directory:
        run(["restic", "restore", "latest", "--tag", "mail-aws", "--host", "mail-aws",
             "--target", directory, "--verify", "--quiet"], env=env, timeout=3600)
        payload = Path(directory) / str(STATE / "payload").lstrip("/")
        verify_payload(payload)
    write_state("restore.json", {"last_success": time.time()})
    metrics({"RestoreAgeSeconds": 0})
    run(["restic", "prune", "--quiet", "--max-unused", "10%"], env=env, timeout=3600)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("reconcile", "health", "canary", "backup", "restore-check"))
    args = parser.parse_args()
    os.umask(0o077)
    STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    lock = None
    try:
        if args.action in ("backup", "restore-check"):
            lock = (STATE / "backup.lock").open("a")
            fcntl.flock(lock, fcntl.LOCK_EX)
        {"reconcile": reconcile, "health": health, "canary": canary, "backup": backup,
         "restore-check": restore_check}[args.action]()
    except Exception as error:
        # Deliberately omit exception text from APIs/SQL: it may contain
        # credentials, recipients, or message content.
        detail = str(error) if isinstance(error, OperationError) else type(error).__name__
        print(f"Mail {args.action} failed: {detail}.", flush=True)
        return 1
    finally:
        if lock:
            lock.close()
    print(f"Mail {args.action} completed.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

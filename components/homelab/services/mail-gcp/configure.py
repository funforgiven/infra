"""Prepare a replacement VM from its restored Stalwart registry and Google Secret Manager."""

import base64
import grp
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

RUNTIME = Path("/run/stalwart-secrets")
STATE = Path("/var/lib/stalwart")


def fetch_secrets():
    project = os.environ["MAIL_GCP_PROJECT"]
    request = urllib.request.Request(
        "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token",
        headers={"Metadata-Flavor": "Google"})
    with urllib.request.urlopen(request, timeout=10) as response:
        token = json.load(response)["access_token"]

    group = grp.getgrnam("stalwart").gr_gid
    RUNTIME.mkdir(mode=0o750, exist_ok=True)
    os.chown(RUNTIME, 0, group)
    os.chmod(RUNTIME, 0o750)
    files = {}
    for name in ("admin", "mailbox", "canary", "backup", "resend", "gcs-hmac"):
        url = f"https://secretmanager.googleapis.com/v1/projects/{project}/secrets/mail-{name}/versions/latest:access"
        with urllib.request.urlopen(urllib.request.Request(
                url, headers={"Authorization": "Bearer " + token}), timeout=20) as response:
            value = base64.b64decode(json.load(response)["payload"]["data"], validate=True).strip()
        if not value:
            raise ValueError(f"Missing value for {name}")
        if name == "gcs-hmac":
            hmac = json.loads(value)
            files["gcs-access"] = hmac["accessId"].encode()
            files["gcs-secret"] = hmac["secret"].encode()
        else:
            files[name if name in ("backup", "canary") else name + "-password"] = value
    for name, value in files.items():
        with tempfile.NamedTemporaryFile(dir=RUNTIME, delete=False) as out:
            out.write(value)
            if name in ("gcs-access", "gcs-secret", "resend-password"):
                os.fchown(out.fileno(), 0, group)
                os.fchmod(out.fileno(), 0o440)
        os.replace(out.name, RUNTIME / name)


def configure_registry():
    user = os.environ["MAIL_DB_USER"]
    probe = subprocess.check_output(
        ["psql", "-XAtw", "-h", "127.0.0.1", "-U", user, "-d", "stalwart",
         "-c", "SELECT EXISTS (SELECT 1 FROM public.s)"], text=True)
    if probe.strip() != "t":
        raise RuntimeError("Restore the PostgreSQL registry before starting the server")
    config = STATE / "config.json"
    config.write_text(json.dumps({"@type": "PostgreSql", "host": "127.0.0.1", "port": 5432,
                                 "authUsername": user, "database": "stalwart", "useTls": False,
                                 "poolMaxConnections": 8}))

    # Only the recovery listener runs while redirecting the restored registry to GCS.
    password = secrets.token_hex(32)
    env = dict(os.environ, STALWART_RECOVERY_MODE="true", STALWART_RECOVERY_MODE_PORT="18080",
               STALWART_RECOVERY_ADMIN="bootstrap:" + password, STALWART_URL="http://127.0.0.1:18080",
               STALWART_USER="bootstrap", STALWART_PASSWORD=password)
    proc = subprocess.Popen(["stalwart", "--config", str(config)], env=env)
    try:
        for _ in range(120):
            if proc.poll() is not None:
                raise RuntimeError("Stalwart recovery listener stopped")
            try:
                with socket.create_connection(("127.0.0.1", 18080), timeout=1):
                    break
            except OSError:
                time.sleep(1)
        else:
            raise RuntimeError("Stalwart recovery listener timed out")
        blob = {"@type": "S3", "bucket": os.environ["MAIL_BLOB_BUCKET"], "keyPrefix": "blobs/",
                "region": {"@type": "Custom", "customRegion": "auto",
                           "customEndpoint": "https://storage.googleapis.com"},
                "accessKey": {"@type": "File", "filePath": str(RUNTIME / "gcs-access")},
                "secretKey": {"@type": "File", "filePath": str(RUNTIME / "gcs-secret")},
                "verifyAfterWrite": True, "allowInvalidCerts": False}
        # The original relay already reads this same runtime path. Preserve DKIM,
        # account credentials, ACME state, listener restrictions and local routing.
        plan = {"@type": "update", "object": "BlobStore", "value": blob}
        subprocess.run(["stalwart-cli", "apply", "--stdin", "--json", "--quiet"], env=env,
                       input=json.dumps(plan), text=True, check=True, timeout=60)
    finally:
        if proc.poll() is None:
            proc.terminate()
        proc.wait(timeout=30)


if __name__ == "__main__":
    if sys.argv[1] == "secrets":
        fetch_secrets()
    elif sys.argv[1] == "registry":
        configure_registry()
    else:
        raise SystemExit("Expected secrets or registry")

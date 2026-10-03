"""Preserve the independent panel's ACME state across disposable EC2 roots."""

import base64
import json
import os
from pathlib import Path, PurePosixPath
import sys
import tempfile

ROOT = Path("/var/lib/acme")
KEY = "infra/mail-admin-acme-state.json"


def restore(document, root=ROOT):
    # Validate the complete object before creating any file. Only ordinary
    # relative paths inside ACME state are allowed, even for a damaged backup.
    files = {}
    for name, encoded in document.items():
        path = PurePosixPath(name)
        if not path.parts or path.is_absolute() or ".." in path.parts:
            raise ValueError("Invalid ACME state path")
        files[path] = base64.b64decode(encoded, validate=True)
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    for path, contents in files.items():
        target = root / path
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if not target.resolve().is_relative_to(root.resolve()):
            raise ValueError("ACME state path escapes its directory")
        with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as output:
            temporary = Path(output.name)
            output.write(contents)
        temporary.replace(target)


def main():
    import boto3
    from botocore.exceptions import ClientError

    os.umask(0o077)
    client = boto3.client("s3", region_name="eu-central-1")
    bucket = os.environ["STALWART_BUCKET"]
    if sys.argv[1] == "restore":
        # Restore only onto a fresh host; never replace live renewal state.
        if (ROOT / ".mail-state-restored").exists():
            return
        try:
            response = client.get_object(Bucket=bucket, Key=KEY)
        except ClientError as error:
            if error.response["Error"]["Code"] != "NoSuchKey":
                raise
        else:
            restore(json.loads(response["Body"].read()))
        ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
        (ROOT / ".mail-state-restored").touch(mode=0o600)
    else:
        document = {
            str(path.relative_to(ROOT)): base64.b64encode(path.read_bytes()).decode()
            for path in ROOT.rglob("*")
            if path.is_file() and not path.is_symlink() and path.name != ".mail-state-restored"
        }
        client.put_object(Bucket=bucket, Key=KEY, Body=json.dumps(document).encode(),
                          ContentType="application/json")
    print("Independent panel certificate state synchronized.")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print("Independent panel certificate state synchronization failed.", file=sys.stderr)
        raise SystemExit(1)

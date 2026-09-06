#!/usr/bin/env python3
"""Publish and verify immutable native images through operator Kubernetes access.

No cloud, Forgejo or SSH credential is installed in the backup container.
Acquire images through authenticated operator tools and record two successful
fresh-guest qualification runs before publishing their public manifest.
"""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time

FILES = {
    "windows": {"disk.qcow2", "image-properties.json"},
    "macos": {"disk.qcow2", "OpenCore.qcow2", "OVMF_CODE.fd", "OVMF_VARS-1920x1080.fd", "manifest.json"},
}


def encoded(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def validate(manifest):
    platform = manifest["platform"]
    if platform not in FILES or set(manifest["files"]) != FILES[platform]:
        raise ValueError("Unexpected native backup files")
    if not re.fullmatch(r"[0-9a-f]{40}", manifest["source_revision"]):
        raise ValueError("A full signed source revision is required")
    runs = manifest["qualification_runs"]
    if len(set(runs)) < 2 or any(type(run) is not int or run <= 0 for run in runs):
        raise ValueError("Two distinct successful fresh-guest qualification runs are required")
    for stamp in (manifest["created_at"], manifest["qualified_at"]):
        if type(stamp) is not int or not 0 < stamp <= time.time() + 300:
            raise ValueError("Invalid native image timestamp")
    for entry in manifest["files"].values():
        if (not re.fullmatch(r"[0-9a-f]{64}", entry["sha256"])
                or type(entry["size"]) is not int or not 0 < entry["size"] <= 80 * 1024**3):
            raise ValueError("Invalid native image checksum or size")


def verify_files(root, manifest):
    validate(manifest)
    for name, entry in manifest["files"].items():
        path = root / name
        if path.is_symlink() or not path.is_file() or path.stat().st_size != entry["size"]:
            raise RuntimeError("Native backup file is missing or has an unexpected size: " + name)
        with path.open("rb") as source:
            if hashlib.file_digest(source, "sha256").hexdigest() != entry["sha256"]:
                raise RuntimeError("Native backup checksum mismatch: " + name)


def verify_index(root):
    index = json.loads((root / "native-index.json").read_text())
    if index.get("schema") != 1 or set(index["platforms"]) != set(FILES):
        raise RuntimeError("Both qualified native image platforms must be restored")
    for platform, entry in index["platforms"].items():
        digest = entry["manifest_sha256"]
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError("Invalid native manifest checksum")
        directory = root / "native" / platform / digest
        if directory.resolve() != directory.absolute():
            raise RuntimeError("Native backup directory must not traverse symlinks")
        raw = (directory / "backup-manifest.json").read_bytes()
        if hashlib.sha256(raw).hexdigest() != digest:
            raise RuntimeError("Native backup manifest checksum mismatch")
        manifest = json.loads(raw)
        if manifest["platform"] != platform:
            raise RuntimeError("Native backup platform mismatch")
        verify_files(directory, manifest)
        print("Verified restored native image, provenance and firmware: " + platform, flush=True)
    return index


def receive(root):
    os.umask(0o077)
    raw = sys.stdin.buffer.readline(16385)
    if len(raw) > 16384 or not raw.endswith(b"\n"):
        raise ValueError("Native manifest exceeds its input limit")
    manifest = json.loads(raw)
    validate(manifest)
    raw = encoded(manifest)
    digest = hashlib.sha256(raw).hexdigest()
    root.mkdir(parents=True, exist_ok=True)
    with (root / ".native-backup.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        total = sum(entry["size"] for entry in manifest["files"].values())
        if shutil.disk_usage(root).free < total + 5 * 1024**3:
            raise RuntimeError("Insufficient backup space; preserve existing recovery images")
        platform = manifest["platform"]
        parent = root / "native" / platform
        parent.mkdir(parents=True, exist_ok=True)
        final = parent / digest
        if final.exists():
            raise RuntimeError("This native backup version already exists; verify it before retrying")
        partial = Path(tempfile.mkdtemp(prefix=".partial-", dir=parent))
        try:
            for name, entry in sorted(manifest["files"].items()):
                checksum, remaining = hashlib.sha256(), entry["size"]
                with (partial / name).open("xb") as output:
                    while remaining:
                        chunk = sys.stdin.buffer.read(min(4 * 1024**2, remaining))
                        if not chunk:
                            raise EOFError("Native image transfer ended early")
                        output.write(chunk)
                        checksum.update(chunk)
                        remaining -= len(chunk)
                    output.flush()
                    os.fsync(output.fileno())
                if checksum.hexdigest() != entry["sha256"]:
                    raise RuntimeError("Transferred native image checksum mismatch: " + name)
            if sys.stdin.buffer.read(1):
                raise ValueError("Unexpected trailing native image data")
            (partial / "backup-manifest.json").write_bytes(raw)
            partial.rename(final)
            path = root / "native-index.json"
            index = json.loads(path.read_text()) if path.exists() else {"schema": 1, "platforms": {}}
            index["platforms"][platform] = {
                "manifest_sha256": digest, "created_at": manifest["created_at"],
                "qualified_at": manifest["qualified_at"], "backed_up_at": int(time.time()),
            }
            temporary = path.with_suffix(".json.partial")
            temporary.write_bytes(encoded(index))
            temporary.replace(path)
            print("Published verified native backup version: " + platform + "/" + digest, flush=True)
        finally:
            if partial.exists():
                shutil.rmtree(partial)


def publish(kubectl, source, manifest_path):
    manifest = json.loads(manifest_path.read_text())
    verify_files(source, manifest)
    # An operator publication is followed by a fresh offsite backup and restore.
    # Avoid changing its index while an existing filesystem backup is scanning.
    backups = json.loads(subprocess.check_output([kubectl, "-n", "velero", "get", "backups", "-o", "json"]))
    if any(item.get("status", {}).get("phase") in {"New", "InProgress", "WaitingForPluginOperations",
            "WaitingForPluginOperationsPartiallyFailed", "Finalizing"} for item in backups["items"]):
        raise RuntimeError("Wait for the active Velero backup before publishing a native image")
    process = subprocess.Popen([kubectl, "-n", "forge", "exec", "-i", "forgejo-0", "-c", "backup", "--",
        "python", "-c", Path(__file__).read_text(), "--receive"], stdin=subprocess.PIPE)
    try:
        process.stdin.write(encoded(manifest))
        for name in sorted(manifest["files"]):
            with (source / name).open("rb") as stream:
                shutil.copyfileobj(stream, process.stdin, length=4 * 1024**2)
        process.stdin.close()
        if process.wait() != 0:
            raise RuntimeError("Native backup receiver failed")
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=30)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--receive", action="store_true")
    mode.add_argument("--verify", action="store_true")
    mode.add_argument("--publish", action="store_true")
    parser.add_argument("--root", type=Path, default=Path("/backups"))
    parser.add_argument("--source", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--kubectl", default="kubectl")
    args = parser.parse_args()
    if args.receive:
        receive(args.root)
    elif args.verify:
        verify_index(args.root)
    elif args.source is None or args.manifest is None:
        parser.error("--publish requires --source and --manifest")
    else:
        publish(args.kubectl, args.source, args.manifest)

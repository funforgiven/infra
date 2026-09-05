#!/usr/bin/env python3
"""Build pinned native Forgejo Runners with a verified Linux Go toolchain.

The Windows and macOS targets compile upstream source without patches. They
still require native workflow qualification before promotion to runner VMs.
"""

import argparse
import hashlib
import json
import os
import shutil
from pathlib import Path
import subprocess
import tarfile
import urllib.request


VERSION = "13.1.0"
SOURCE_URL = f"https://code.forgejo.org/forgejo/runner/archive/v{VERSION}.tar.gz"
SOURCE_SHA256 = "bdece01a00354bb29de4e36b6c72afae9ed571ed1fba1905d01bc8961de41819"
GO_VERSION = "1.26.8"
GO_URL = f"https://go.dev/dl/go{GO_VERSION}.linux-amd64.tar.gz"
GO_SHA256 = "d0f743b33e8d8945e6b1f432edd15785c70507121d6e2a723b21285eddf8b57b"


def checksum(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def download(url, target, expected):
    if not target.exists():
        temporary = target.with_suffix(".partial")
        try:
            with urllib.request.urlopen(url, timeout=300) as response, temporary.open("wb") as output:
                while chunk := response.read(1024 * 1024):
                    output.write(chunk)
            if checksum(temporary) != expected:
                raise RuntimeError(f"checksum mismatch for {target.name}")
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
    if checksum(target) != expected:
        raise RuntimeError(f"checksum mismatch for cached {target.name}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-directory", type=Path, required=True)
    parser.add_argument("--platform", action="append", choices=("linux-amd64", "windows-amd64", "darwin-amd64", "darwin-arm64"))
    args = parser.parse_args()
    root = args.work_directory.resolve()
    root.mkdir(parents=True, exist_ok=True)
    output = root / "artifacts"
    output.mkdir(exist_ok=True)
    for name, url, expected in (("source", SOURCE_URL, SOURCE_SHA256), ("toolchain", GO_URL, GO_SHA256)):
        archive = root / (name + ".tar.gz")
        download(url, archive, expected)
        # Re-extract verified inputs on each run to discard local source edits.
        if (root / name).exists():
            shutil.rmtree(root / name)
        with tarfile.open(archive) as source:
            source.extractall(root / name, filter="data")
    source_dir, = [item for item in (root / "source").iterdir() if item.is_dir()]
    environment = {**os.environ, "GOTOOLCHAIN": "local", "CGO_ENABLED": "0",
                   "GOCACHE": str(root / "go-cache"), "GOPATH": str(root / "go-path")}
    flags = ["-buildvcs=false", "-mod=readonly", "-trimpath", "-tags", "netgo osusergo",
             "-ldflags", f"-s -w -X code.forgejo.org/forgejo/runner/v13/internal/pkg/ver.version=v{VERSION}"]
    binaries = {}
    for platform in args.platform or ("linux-amd64", "windows-amd64", "darwin-amd64"):
        system, arch = platform.split("-")
        binary = output / f"forgejo-runner-{VERSION}-{platform}{'.exe' if system == 'windows' else ''}"
        subprocess.run([str(root / "toolchain/go/bin/go"), "build", *flags, "-o", str(binary), "."],
                       cwd=source_dir, env={**environment, "GOOS": system, "GOARCH": arch}, check=True)
        binaries[binary.name] = checksum(binary)
        print(f"Built {platform}: {binaries[binary.name]}", flush=True)
    (output / "provenance.json").write_text(json.dumps({"runner_version": VERSION,
        "source": {"url": SOURCE_URL, "sha256": SOURCE_SHA256},
        "toolchain": {"url": GO_URL, "sha256": GO_SHA256}, "build_flags": flags,
        "artifacts": binaries, "native_execution_qualified": False}, indent=2) + "\n")


if __name__ == "__main__":
    main()

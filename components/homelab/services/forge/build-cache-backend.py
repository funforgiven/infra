#!/usr/bin/env python3
"""Build the dedicated cache backend from pinned Runner and Go archives.

Job runners remain upstream binaries. Pass the emitted backend to cache-image.nix
with the repository-pinned pkgs to build the small service image.
"""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile

spec = importlib.util.spec_from_file_location("runner_build", Path(__file__).with_name("build-runners.py"))
upstream = importlib.util.module_from_spec(spec)
spec.loader.exec_module(upstream)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-directory", required=True, type=Path)
    args = parser.parse_args()
    root = args.work_directory.resolve()
    root.mkdir(parents=True, exist_ok=True)
    patch = Path(__file__).with_name("runner-cache-isolation.patch")
    for name, url, digest in (("source", upstream.SOURCE_URL, upstream.SOURCE_SHA256),
                              ("toolchain", upstream.GO_URL, upstream.GO_SHA256)):
        archive = root / (name + ".tar.gz")
        upstream.download(url, archive, digest)
        if (root / name).exists():
            shutil.rmtree(root / name)
        with tarfile.open(archive) as stream:
            stream.extractall(root / name, filter="data")
    source, = [path for path in (root / "source").iterdir() if path.is_dir()]
    subprocess.run(["patch", "--fuzz=0", "-p1", "-i", str(patch.resolve())], cwd=source, check=True)
    go = str(root / "toolchain/go/bin/go")
    env = {**os.environ, "GOTOOLCHAIN": "local", "CGO_ENABLED": "0", "GOMAXPROCS": "2", "GOOS": "linux", "GOARCH": "amd64",
           "GOCACHE": str(root / "go-cache"), "GOPATH": str(root / "go-path")}
    test = [go, "test", "-p", "2", "-timeout", "180s", "-mod=readonly", "-count=1", "-json", "./act/artifactcache"]
    with (root / "tests.jsonl").open("w") as log:
        subprocess.run(test, cwd=source, env=env, stdout=log, check=True)
    flags = ["-buildvcs=false", "-mod=readonly", "-trimpath", "-tags", "netgo osusergo", "-ldflags",
             "-s -w -X code.forgejo.org/forgejo/runner/v13/internal/pkg/ver.version=v13.1.0+cache-isolation.1"]
    binary = root / "forgejo-runner-13.1.0-cache-isolation-linux-amd64"
    subprocess.run([go, "build", *flags, "-o", str(binary), "."], cwd=source, env=env, check=True)
    (root / "provenance.json").write_text(json.dumps({
        "source_sha256": upstream.SOURCE_SHA256, "go_sha256": upstream.GO_SHA256,
        "patch_sha256": upstream.checksum(patch), "binary_sha256": upstream.checksum(binary),
        "flags": flags, "test_command": test, "test_log_sha256": upstream.checksum(root / "tests.jsonl"),
    }, indent=2) + "\n")
    print(binary)


if __name__ == "__main__":
    main()

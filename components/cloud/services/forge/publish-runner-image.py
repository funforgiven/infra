#!/usr/bin/env python3
"""Publish a Nix-built infrastructure image to Forgejo without disk auth files."""

import argparse
import base64
import json
import os
from pathlib import Path
import subprocess

import yaml


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path, help="Nix-built Docker archive")
    parser.add_argument("--destination", default="runner-linux:13.1.0", choices=[
        "runner-linux:13.1.0", "libvirt-tpm:2026.1-swtpm-0.10.1"])
    args = parser.parse_args()
    destination = "git.fahrican.com/forge-runner/" + args.destination
    secret = yaml.safe_load(subprocess.run(["sops", "decrypt",
        "deployments/homelab/cloud/services/46-forge/runtime.sops.yaml"],
        capture_output=True, check=True).stdout)["stringData"]
    authentication = base64.b64encode(("forge-runner:" + secret["forgejo-runner-password"]).encode()).decode()
    descriptor = os.memfd_create("forge-registry-auth", os.MFD_CLOEXEC)
    try:
        os.write(descriptor, json.dumps({"auths": {"git.fahrican.com": {"auth": authentication}}}).encode())
        os.lseek(descriptor, 0, os.SEEK_SET)
        subprocess.run(["skopeo", "copy", "--quiet", "--dest-authfile", f"/proc/self/fd/{descriptor}",
            "docker-archive:" + str(args.image.resolve()),
            "docker://" + destination], pass_fds=(descriptor,), check=True)
        result = subprocess.run(["skopeo", "inspect", "--authfile", f"/proc/self/fd/{descriptor}",
            "--format", "{{.Digest}}", "docker://" + destination],
            pass_fds=(descriptor,), capture_output=True, text=True, check=True)
        print("Published " + destination + "@" + result.stdout.strip())
    finally:
        os.close(descriptor)


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError:
        raise SystemExit("Image publication failed; SOPS diagnostics suppressed.") from None

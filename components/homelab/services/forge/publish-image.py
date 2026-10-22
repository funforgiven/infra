#!/usr/bin/env python3
"""Publish a Nix-built forge image to the Forgejo registry without disk auth files.

The destination is the archive's own repository tag, so the Nix expression is
the single source of the image name and version:

    nix build .#forge-cache-image && components/homelab/services/forge/publish-image.py result
"""

import argparse
import base64
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tarfile

sys.path.insert(0, str(Path.cwd() / "components/homelab/operations"))
from encrypted_inputs import decrypt, values  # noqa: E402


def destination(image):
    with tarfile.open(image) as archive:
        manifest = json.load(archive.extractfile("manifest.json"))
    tags = [tag for entry in manifest for tag in entry.get("RepoTags") or []]
    if len(tags) != 1 or not re.fullmatch(r"git\.fahrican\.com/forge-runner/[a-z0-9-]+:[A-Za-z0-9._-]+", tags[0]):
        raise SystemExit("The image archive must carry exactly one git.fahrican.com/forge-runner tag.")
    return tags[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("image", type=Path, help="Nix-built Docker archive")
    args = parser.parse_args()
    target = destination(args.image)
    secret = values(decrypt("deployments/homelab/cluster/apps/forge/runtime.sops.yaml")[0])
    authentication = base64.b64encode(("forge-runner:" + secret["forgejo-runner-password"]).encode()).decode()
    descriptor = os.memfd_create("forge-registry-auth", os.MFD_CLOEXEC)
    try:
        os.write(descriptor, json.dumps({"auths": {"git.fahrican.com": {"auth": authentication}}}).encode())
        os.lseek(descriptor, 0, os.SEEK_SET)
        subprocess.run(["skopeo", "copy", "--quiet", "--dest-authfile", f"/proc/self/fd/{descriptor}",
            "docker-archive:" + str(args.image.resolve()),
            "docker://" + target], pass_fds=(descriptor,), check=True)
        result = subprocess.run(["skopeo", "inspect", "--authfile", f"/proc/self/fd/{descriptor}",
            "--format", "{{.Digest}}", "docker://" + target],
            pass_fds=(descriptor,), capture_output=True, text=True, check=True)
        print("Published " + target + "@" + result.stdout.strip())
    finally:
        os.close(descriptor)


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError:
        raise SystemExit("Image publication failed; SOPS diagnostics suppressed.") from None

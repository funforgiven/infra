#!/usr/bin/env python3
"""Reconcile encrypted Forgejo runtime credentials from undercloud ZITADEL outputs.

Run in the infrastructure development shell with undercloud kubectl configured.
Secrets travel through captured pipes; only SOPS ciphertext is written to disk.
"""

import argparse
import base64
import json
import secrets
import subprocess
from pathlib import Path

import yaml


def run(argv, data=None):
    return subprocess.run(argv, input=data, capture_output=True, check=True).stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kubectl", default="kubectl")
    args = parser.parse_args()
    target = Path("deployments/homelab/cloud/services/46-forge/runtime.sops.yaml")
    if target.exists():
        document = yaml.safe_load(run(["sops", "decrypt", str(target)]))
    else:
        document = {"apiVersion": "v1", "kind": "Secret", "metadata": {
            "name": "forge-runtime", "namespace": "forge"}, "type": "Opaque", "stringData": {}}
    values = document["stringData"]
    # Secrets recover from SOPS; the complete application archive is encrypted
    # by Kopia. Avoid also putting plaintext Secret objects in Velero metadata.
    document["metadata"].setdefault("labels", {})["velero.io/exclude-from-backup"] = "true"
    for name in ("forgejo-secret-key", "forgejo-internal-token", "forgejo-admin-password",
                 "forgejo-metrics-token"):
        values.setdefault(name, secrets.token_hex(32))
    for name in tuple(values):
        if name.startswith("woodpecker-"):
            del values[name]
    for name in ("forgejo-lfs-secret", "forgejo-oauth-secret"):
        values.setdefault(name, secrets.token_urlsafe(32))
    outputs = json.loads(run([args.kubectl, "-n", "tofu-system", "get", "secret",
                             "zitadel-identity-outputs", "-o", "json"]))["data"]
    for key in ("id", "secret"):
        values[f"forgejo-oidc-client-{key}"] = base64.b64decode(outputs[f"forgejo_client_{key}"]).decode()
    ciphertext = run(["sops", "encrypt", "--filename-override", str(target),
                      "--input-type", "yaml", "--output-type", "yaml", "/dev/stdin"],
                     yaml.safe_dump(document, sort_keys=False).encode())
    target.write_bytes(ciphertext)
    print("Reconciled encrypted Forgejo runtime credentials.")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError:
        raise SystemExit("Enrollment failed; check SOPS and undercloud access. Secret output was suppressed.") from None

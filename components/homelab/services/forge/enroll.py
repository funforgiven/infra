#!/usr/bin/env python3
"""Reconcile encrypted Forgejo runtime credentials from preserved ZITADEL provider state.

Run in the infrastructure development shell from the repository root.
Secrets travel through captured pipes; only SOPS ciphertext is written to disk.
"""

import argparse
import base64
import json
import secrets
import subprocess
import sys
from pathlib import Path

import yaml


def run(argv, data=None):
    return subprocess.run(argv, input=data, capture_output=True, check=True).stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    args = parser.parse_args()
    target = Path("deployments/homelab/cluster/apps/forge/runtime.sops.yaml")
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
    sys.path.insert(0, str(Path.cwd() / "components/homelab/operations"))
    from provider_state import outputs as provider_outputs
    outputs = {key: base64.b64encode(str(item["value"]).encode()).decode()
               for key, item in provider_outputs("identity").items()}
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
        raise SystemExit("Enrollment failed; check SOPS and archived provider state. Secret output was suppressed.") from None

#!/usr/bin/env python3
"""Reconcile encrypted Forgejo runtime credentials from the ZITADEL provider state.

Run in the infrastructure development shell from the repository root.
Secrets travel through captured pipes; only SOPS ciphertext is written to disk.
"""

import argparse
import secrets
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd() / "components/homelab/operations"))
from encrypted_inputs import decrypt, save  # noqa: E402
from provider_state import outputs as provider_outputs  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    target = Path("deployments/homelab/cluster/apps/forge/runtime.sops.yaml")
    if target.exists():
        document = decrypt(target)[0]
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
    for name in ("forgejo-lfs-secret", "forgejo-oauth-secret"):
        values.setdefault(name, secrets.token_urlsafe(32))
    outputs = provider_outputs("identity")
    for key in ("id", "secret"):
        values[f"forgejo-oidc-client-{key}"] = str(outputs[f"forgejo_client_{key}"]["value"])
    save(Path.cwd(), target, [document])
    print("Reconciled encrypted Forgejo runtime credentials.")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError:
        raise SystemExit("Enrollment failed; check SOPS and the provider state. Secret output was suppressed.") from None

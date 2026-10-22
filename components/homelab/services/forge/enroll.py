#!/usr/bin/env python3
"""Reconcile locally generated encrypted Forgejo runtime credentials.

Run in the infrastructure development shell from the repository root.
Secrets travel through captured pipes; only SOPS ciphertext is written to disk.
The ZITADEL OIDC client comes from the identity-credentials app.
"""

import argparse
import secrets
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd() / "components/homelab/operations"))
from encrypted_inputs import decrypt, save, secret  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    target = Path("deployments/homelab/cluster/apps/forge/runtime.sops.yaml")
    if target.exists():
        document = decrypt(target)[0]
    else:
        document = secret("forge-runtime", "forge", {})
    values = document["stringData"]
    # Secrets recover from SOPS; keep plaintext Secret objects out of Velero.
    document["metadata"].setdefault("labels", {})["velero.io/exclude-from-backup"] = "true"
    for name in ("forgejo-secret-key", "forgejo-internal-token", "forgejo-admin-password",
                 "forgejo-metrics-token"):
        values.setdefault(name, secrets.token_hex(32))
    for name in ("forgejo-lfs-secret", "forgejo-oauth-secret"):
        values.setdefault(name, secrets.token_urlsafe(32))
    save(Path.cwd(), target, [document])
    print("Reconciled encrypted Forgejo runtime credentials.")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError:
        raise SystemExit("Enrollment failed; check SOPS. Secret output was suppressed.") from None

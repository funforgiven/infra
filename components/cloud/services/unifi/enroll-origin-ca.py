#!/usr/bin/env python3
"""Enroll only the PUBLIC origin CA over a previously pinned SSH identity."""
import argparse
from pathlib import Path
import subprocess
import tempfile

import yaml

ROOT = Path(__file__).resolve().parents[4]
DESTINATION = ROOT / "deployments/homelab/cloud/services/24-unifi"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--identity-file", default="/run/secrets/github-ssh-key")
    parser.add_argument("--known-hosts-file", help="Optional file containing the console-verified host key")
    args = parser.parse_args()
    known_hosts = ["-o", f"UserKnownHostsFile={args.known_hosts_file}"] if args.known_hosts_file else []
    result = subprocess.run(
        ["ssh", "-i", args.identity_file, "-o", "IdentitiesOnly=yes",
         "-o", "IdentityAgent=none", "-o", "StrictHostKeyChecking=yes",
         "-o", "BatchMode=yes", *known_hosts, "ubuntu@10.21.40.127",
         "sudo -n cat /var/lib/unifi-proxy/tls/ca.crt"],
        capture_output=True, check=True,
    )
    certificate = result.stdout.decode("ascii")
    if not certificate.startswith("-----BEGIN CERTIFICATE-----") or len(certificate) > 16384:
        raise SystemExit("The host did not return one public PEM certificate")
    with tempfile.TemporaryDirectory() as temporary:
        ca = Path(temporary) / "ca.crt"
        ca.write_text(certificate)
        subprocess.run(["openssl", "verify", "-CAfile", str(ca), str(ca)], check=True)
        subprocess.run(["openssl", "x509", "-checkend", "2592000", "-noout", "-in", str(ca)], check=True)
    document = {
        "apiVersion": "v1", "kind": "ConfigMap",
        "metadata": {"name": "unifi-origin-ca", "namespace": "unifi"},
        "data": {"ca.crt": certificate},
    }
    (DESTINATION / "origin-ca.yaml").write_text(yaml.safe_dump(document, sort_keys=False))
    path = DESTINATION / "kustomization.yaml"
    kustomization = yaml.safe_load(path.read_text())
    if "origin-ca.yaml" not in kustomization["resources"]:
        kustomization["resources"].append("origin-ca.yaml")
        path.write_text(yaml.safe_dump(kustomization, sort_keys=False))
    print("Public CA enrolled; review and commit origin-ca.yaml and kustomization.yaml.")


if __name__ == "__main__":
    main()

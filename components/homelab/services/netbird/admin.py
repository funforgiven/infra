#!/usr/bin/env python3
"""Rotate NetBird automation credentials; policy and routing are reconciled from Git."""

import argparse
import datetime
import json
import os
import secrets
import urllib.request
from pathlib import Path

import yaml
# components/homelab/operations, on PYTHONPATH from the netbird-admin wrapper.
from encrypted_inputs import decrypt_one as decrypt, save_one as encrypt, secret

DEPLOYMENT = Path("deployments/homelab/cluster/apps/netbird")
POLICY = Path("deployments/homelab/credentials/netbird-policy")
BOOTSTRAP = Path("secrets/netbird-bootstrap.yaml")


def token_alerts(state):
    rules = []
    for name in ("tofu-netbird", "kubernetes-netbird"):
        expiry = datetime.datetime.fromisoformat(state[name]["personal_access_token"]["expiration_date"])
        rules.append({
            "alert": "NetBirdAutomationCredentialExpiring",
            "expr": f"vector({int(expiry.timestamp())}) - time() < 2592000",
            "for": "1h", "labels": {"severity": "warning", "credential": name},
            "annotations": {
                "summary": "NetBird automation credential expires within 30 days",
                "description": "Run netbird-admin rotate-credentials and reconcile the encrypted Git inputs.",
            },
        })
    document = {
        "apiVersion": "monitoring.coreos.com/v1", "kind": "PrometheusRule",
        "metadata": {"name": "netbird-credentials", "namespace": "netbird", "labels": {"release": "kube-prometheus-stack"}},
        "spec": {"groups": [{"name": "netbird-credentials", "rules": rules}]},
    }
    (DEPLOYMENT / "server/credentials-monitoring.yaml").write_text(yaml.safe_dump(document, sort_keys=False))


def api(base, path, token=None, body=None, method=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Token " + token
    request = urllib.request.Request(
        base + "/api" + path,
        data=None if body is None else json.dumps(body).encode(),
        headers=headers, method=method,
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        data = response.read()
        return json.loads(data) if data else None


def rotate_credentials():
    state = decrypt(BOOTSTRAP)
    for name in ("tofu-netbird", "kubernetes-netbird"):
        current = state[name]
        generated = api(
            "https://netbird-api.fahrican.com",
            f"/users/{current['user_id']}/tokens", current["plain_token"],
            {"name": "gitops-rotation", "expires_in": 365},
        )
        # Save before publishing. Old credentials remain valid until the new
        # reconciliation is verified, so interruption does not lock out GitOps.
        state[name] = {"user_id": current["user_id"], **generated}
        encrypt(BOOTSTRAP, state)
    encrypt(POLICY / "credentials.sops.yaml", secret("netbird-policy-credentials", "tofu-system", {
        "netbird_token": state["tofu-netbird"]["plain_token"],
        "default_policy_id": state["default_policy_id"],
    }))
    encrypt(DEPLOYMENT / "operator/token.sops.yaml", secret("netbird-operator-token", "netbird-routing", {
        "NB_API_KEY": state["kubernetes-netbird"]["plain_token"],
    }))
    path = DEPLOYMENT / "operator/operator.yaml"
    documents = list(yaml.safe_load_all(path.read_text()))
    helm = next(doc for doc in documents if doc["kind"] == "HelmRelease")
    helm["spec"]["values"]["operator"]["podAnnotations"] = {
        "netbird.fahrican.com/credential-generation": secrets.token_hex(8),
    }
    path.write_text(yaml.safe_dump_all(documents, sort_keys=False))
    token_alerts(state)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("rotate-credentials",))
    parser.parse_args()
    if not Path(".sops.yaml").exists():
        raise ValueError("run from the repository root")
    rotate_credentials()
    print("NetBird credentials rotated; credentials were not printed.")


if __name__ == "__main__":
    os.umask(0o077)
    try:
        main()
    except Exception:  # noqa: BLE001 - errors from providers may contain credentials
        raise SystemExit("NetBird operation failed; secret diagnostics suppressed. Check prerequisites and rerun.") from None

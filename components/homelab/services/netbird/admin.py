#!/usr/bin/env python3
"""NetBird enrollment and credential rotation; policy and routing are reconciled from Git."""

import argparse
import base64
import datetime
import json
import os
import re
import secrets
import subprocess
import urllib.request
from pathlib import Path

import yaml
import restore_check
# components/homelab/operations, on PYTHONPATH from the netbird-admin wrapper.
from encrypted_inputs import decrypt_one as decrypt, save_one as encrypt, secret

DEPLOYMENT = Path("deployments/homelab/cluster/apps/netbird")
POLICY = Path("deployments/homelab/credentials/netbird-policy")
BOOTSTRAP = Path("secrets/netbird-bootstrap.yaml")


def run(command, data=None):
    return subprocess.run(command, input=data, capture_output=True, check=True).stdout


def add_resource(kustomization, filename):
    document = yaml.safe_load(kustomization.read_text())
    if filename not in document["resources"]:
        document["resources"].append(filename)
        kustomization.write_text(yaml.safe_dump(document, sort_keys=False))


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
    add_resource(DEPLOYMENT / "server/kustomization.yaml", "credentials-monitoring.yaml")


def prepare():
    path = DEPLOYMENT / "server/runtime.sops.yaml"
    if path.exists():
        return
    password = secrets.token_hex(32)
    # NetBird's embedded Dex DSN parser accepts sslmode but does not forward
    # sslrootcert. Use the mounted CNPG CA as Go's system trust root as well.
    dsn = (
        "host=netbird-postgres-rw.netbird.svc port=5432 user=netbird "
        f"password={password} sslmode=verify-full "
        "sslrootcert=/etc/postgres-ca/ca.crt"
    )
    config = {"server": {
        "listenAddress": ":8080",
        "exposedAddress": "https://netbird.fahrican.com:443",
        "stuns": [{"uri": "stun:netbird-stun.fahrican.com:3478"}], "metricsPort": 9090,
        "healthcheckAddress": ":9000", "logLevel": "info", "logFile": "console",
        "dataDir": "/var/lib/netbird",
        "authSecret": secrets.token_urlsafe(48),
        "disableAnonymousMetrics": True, "disableGeoliteUpdate": True,
        "auth": {
            "issuer": "https://netbird.fahrican.com/oauth2",
            "localAuthDisabled": False,
            "sessionCookieEncryptionKey": base64.b64encode(secrets.token_bytes(32)).decode(),
            "dashboardRedirectURIs": ["https://netbird-api.fahrican.com/nb-auth"],
            "cliRedirectURIs": ["http://localhost:53000/", "http://localhost:54000/"],
        },
        "store": {
            "engine": "postgres", "dsn": dsn + " dbname=netbird",
            "encryptionKey": base64.b64encode(secrets.token_bytes(32)).decode(),
        },
        "activityStore": {"engine": "postgres", "dsn": dsn + " dbname=netbird_events"},
        "authStore": {"engine": "postgres", "dsn": dsn + " dbname=netbird_auth"},
    }}
    encrypt(path, secret("netbird-runtime", "netbird", {
        "username": "netbird", "password": password,
        "config.yaml": yaml.safe_dump(config, sort_keys=False),
    }, "kubernetes.io/basic-auth"))
    if not BOOTSTRAP.exists():
        encrypt(BOOTSTRAP, {
            "email": "netbird-bootstrap@fahrican.com",
            "password": secrets.token_urlsafe(48),
        })


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


def bind_bootstrap_account(account_id):
    """Bind /setup's domain-less account before the first external SSO login."""
    if not re.fullmatch(r"[a-z0-9]{20}", account_id):
        raise ValueError("unexpected NetBird account identifier")
    cluster = restore_check.get("netbird", "cluster", "netbird-postgres")
    # Combined server 0.80.0 groups SSO users under DefaultSelfHostedDomain,
    # but /setup creates an account without that domain. A PAT cannot fill it.
    # Refuse to bind if SSO has already created a second account.
    query = f"""
BEGIN;
LOCK TABLE accounts IN SHARE ROW EXCLUSIVE MODE;
DO $bind$
BEGIN
  IF (SELECT count(*) FROM accounts) <> 1 OR NOT EXISTS (
    SELECT 1 FROM accounts WHERE id = '{account_id}'
      AND (domain = '' OR domain = 'netbird.selfhosted')
  ) THEN
    RAISE EXCEPTION 'Expected the sole bootstrap account; repair split accounts first';
  END IF;
  UPDATE accounts SET domain = 'netbird.selfhosted', domain_category = 'private',
    is_domain_primary_account = true WHERE id = '{account_id}';
END $bind$;
COMMIT;
"""
    run([
        "kubectl", "-n", "netbird", "exec", "-i", cluster["status"]["currentPrimary"],
        "-c", "postgres", "--", "psql", "-v", "ON_ERROR_STOP=1", "-d", "netbird",
    ], query.encode())


def bootstrap(base):
    # Loopback only. The unauthenticated setup endpoint is never published.
    if base != "http://127.0.0.1:18080":
        raise ValueError("bootstrap requires the documented local port-forward")
    state = decrypt(BOOTSTRAP)
    status = api(base, "/instance")
    if status["setup_required"]:
        result = api(base, "/setup", body={
            "email": state["email"], "password": state["password"],
            "name": "Bootstrap", "create_pat": True, "pat_expire_in": 7,
        })
        state["token"] = result["personal_access_token"]
        state["owner_id"] = result["user_id"]
        # Persist the only returned copy before any further network mutation.
        encrypt(BOOTSTRAP, state)
    token = state["token"]
    accounts = api(base, "/accounts", token)
    if len(accounts) != 1:
        raise ValueError("bootstrap must own exactly one account")
    bind_bootstrap_account(accounts[0]["id"])
    policies = api(base, "/policies", token)
    default = next(policy for policy in policies if policy["name"] == "Default")
    if default["enabled"]:
        body = {key: value for key, value in default.items() if key != "id"}
        body["enabled"] = False
        for rule in body["rules"]:
            rule["enabled"] = False
            # GET expands group objects; PUT accepts only their IDs.
            for direction in ("sources", "destinations"):
                rule[direction] = [group["id"] for group in rule[direction]]
        api(base, "/policies/" + default["id"], token, body, "PUT")
    state["default_policy_id"] = default["id"]
    users = api(base, "/users", token)
    for name in ("tofu-netbird", "kubernetes-netbird"):
        if name in state:
            continue
        user = next((user for user in users if user["name"] == name and user["is_service_user"]), None)
        if user is None:
            user = api(base, "/users", token, {
                "name": name, "is_service_user": True, "role": "admin", "auto_groups": [],
            })
        generated = api(base, f"/users/{user['id']}/tokens", token, {
            "name": "gitops-enrollment", "expires_in": 365,
        })
        state[name] = {"user_id": user["id"], **generated}
        encrypt(BOOTSTRAP, state)
    encrypt(POLICY / "credentials.sops.yaml", secret("netbird-policy-credentials", "tofu-system", {
        "netbird_token": state["tofu-netbird"]["plain_token"],
        "default_policy_id": state["default_policy_id"],
    }))
    encrypt(DEPLOYMENT / "operator/token.sops.yaml", secret("netbird-operator-token", "netbird-routing", {
        "NB_API_KEY": state["kubernetes-netbird"]["plain_token"],
    }))
    add_resource(DEPLOYMENT / "operator/kustomization.yaml", "token.sops.yaml")
    token_alerts(state)


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


def close_bootstrap():
    state = decrypt(BOOTSTRAP)
    users = api("https://netbird-api.fahrican.com", "/users", state["tofu-netbird"]["plain_token"])
    if not any(
        not user["is_service_user"] and user["id"] != state["owner_id"]
        and user.get("idp_id") and user["idp_id"] != "local"
        and not user.get("is_blocked", False) and not user.get("pending_approval", False)
        for user in users
    ):
        raise ValueError("verify an approved SSO user in the bootstrap account before closing local login")
    path = DEPLOYMENT / "server/runtime.sops.yaml"
    document = decrypt(path)
    config = yaml.safe_load(document["stringData"]["config.yaml"])
    config["server"]["auth"]["localAuthDisabled"] = True
    document["stringData"]["config.yaml"] = yaml.safe_dump(config, sort_keys=False)
    encrypt(path, document)
    path = DEPLOYMENT / "server/workload.yaml"
    documents = list(yaml.safe_load_all(path.read_text()))
    workload = next(doc for doc in documents if doc["kind"] == "Deployment")
    workload["spec"]["template"]["metadata"]["annotations"] = {
        "netbird.fahrican.com/auth-mode": "sso",
    }
    for env in workload["spec"]["template"]["spec"]["containers"][0]["env"]:
        if env["name"] == "NB_SETUP_PAT_ENABLED":
            env["value"] = "false"
    path.write_text(yaml.safe_dump_all(documents, sort_keys=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "bootstrap", "close-bootstrap", "rotate-credentials", "restore-check"))
    args = parser.parse_args()
    if not Path(".sops.yaml").exists():
        raise ValueError("run from the repository root")
    actions = {
        "prepare": prepare,
        "bootstrap": lambda: bootstrap("http://127.0.0.1:18080"),
        "close-bootstrap": close_bootstrap,
        "rotate-credentials": rotate_credentials,
        "restore-check": restore_check.restore_check,
    }
    actions[args.command]()
    print(f"NetBird {args.command} complete; credentials were not printed.")


if __name__ == "__main__":
    os.umask(0o077)
    try:
        main()
    except Exception:  # noqa: BLE001 - errors from providers may contain credentials
        raise SystemExit("NetBird operation failed; secret diagnostics suppressed. Check prerequisites and rerun.") from None

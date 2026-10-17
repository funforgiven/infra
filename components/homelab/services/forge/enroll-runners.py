#!/usr/bin/env python3
"""Enroll the private Actions test repository and least-scope CI credentials.

Requires the infrastructure development shell. API responses and plaintext
credentials stay in memory; only encrypted Kubernetes Secrets are persisted.
"""

import base64
import json
from pathlib import Path
import secrets
import subprocess
import sys

import requests

sys.path.insert(0, str(Path.cwd() / "components/homelab/operations"))
from encrypted_inputs import decrypt, save  # noqa: E402

ROOT = Path("deployments/homelab/cluster/apps/forge")
BASE = "https://git.fahrican.com/api/v1"


def call(session, method, path, body=None, expected=(200, 201, 204)):
    response = session.request(method, BASE + path, json=body, timeout=30)
    if response.status_code not in expected:
        raise RuntimeError(f"Forgejo {method} {path}: HTTP {response.status_code}")
    return response.json() if response.content else {}


def main():
    runtime = decrypt(ROOT / "runtime.sops.yaml")[0]
    values = runtime["stringData"]
    admin = requests.Session()
    admin.auth = ("forge-admin", values["forgejo-admin-password"])
    account = call(admin, "GET", "/users/forge-runner", expected=(200, 404))
    if account.get("login") != "forge-runner":
        values.setdefault("forgejo-runner-password", secrets.token_hex(32))
        save(Path.cwd(), ROOT / "runtime.sops.yaml", [runtime])
        call(admin, "POST", "/admin/users", {"username": "forge-runner", "email": "forge-runner@fahrican.com",
            "password": values["forgejo-runner-password"], "must_change_password": False,
            "send_notify": False, "visibility": "private"})
    owner = requests.Session()
    owner.auth = ("forge-runner", values["forgejo-runner-password"])
    repository = "forge-runner/runner-qualification"
    repo = call(owner, "GET", "/repos/" + repository, expected=(200, 404))
    if repo.get("name") != "runner-qualification":
        call(owner, "POST", "/user/repos", {"name": "runner-qualification", "private": True,
            "description": "Infrastructure-owned Actions execution and recovery qualification",
            "auto_init": True, "default_branch": "main"})
    call(owner, "PATCH", "/repos/" + repository, {"has_actions": True})
    for target, name, scopes, repositories, namespace in [
        (ROOT / "runner-qualification.sops.yaml", "runner-qualification", ["write:repository"],
         [{"owner": "forge-runner", "name": "runner-qualification"}], "forge-ci"),
        (ROOT / "runner-registry.sops.yaml", "runner-registry", ["read:package"], [], "forge-ci"),
    ]:
        if target.exists():
            print(f"{name}: encrypted credential already enrolled")
            continue
        options = {"name": name, "scopes": scopes}
        if repositories:
            options["repositories"] = repositories
        token = call(owner, "POST", "/users/forge-runner/tokens", options)
        document = {"apiVersion": "v1", "kind": "Secret", "metadata": {"name": name, "namespace": namespace,
                    "labels": {"velero.io/exclude-from-backup": "true"}},
                    "type": "Opaque", "stringData": {"token": token["sha1"]}}
        if name == "runner-registry":
            document["type"] = "kubernetes.io/dockerconfigjson"
            authentication = base64.b64encode(("forge-runner:" + token["sha1"]).encode()).decode()
            document["stringData"] = {".dockerconfigjson": json.dumps({"auths": {
                "git.fahrican.com": {"auth": authentication}}})}
        try:
            save(Path.cwd(), target, [document])
        except Exception:
            call(owner, "DELETE", f'/users/forge-runner/tokens/{token["id"]}')
            raise
        print(f"{name}: created and encrypted")
    print("Private runner-qualification repository and scoped CI credentials are enrolled.")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError:
        raise SystemExit("SOPS operation failed; secret-bearing diagnostics suppressed.") from None

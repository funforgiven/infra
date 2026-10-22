#!/usr/bin/env python3
"""Copy ZITADEL OIDC client credentials from identity outputs into consumer SOPS files.

Usage: nix run .#tofu -- identity output -json | nix run .#identity-credentials
"""
import json
import os
from pathlib import Path
import sys

import yaml

from encrypted_inputs import decrypt, save, values

# NetBird reads its client from the identity state directly.
OIDC_APPS = ("forgejo", "grafana", "sftpgo", "navidrome", "audiomuse", "matrix")
ISSUER = "https://auth.cloud.fahrican.com"


def identity_values(outputs):
    """Validate the complete output before any encrypted file changes."""
    result = {}
    for app in OIDC_APPS:
        for field in ("id", "secret"):
            key = app + "_client_" + field
            item = outputs.get(key)
            if not isinstance(item, dict) or not isinstance(item.get("value"), str) or not item["value"]:
                raise ValueError("incomplete identity outputs; diagnostics suppressed")
            result[key] = item["value"]
    return result


def update_document(documents, name, change):
    document = next(d for d in documents if d["metadata"]["name"] == name)
    data = values(document)
    change(data)
    document.pop("data", None)
    document["stringData"] = data


def client(current, app, prefix, suffix=str.lower):
    return {prefix + suffix(field): current[app + "_client_" + field] for field in ("id", "secret")}


def set_matrix_upstream(current):
    def change(data):
        config = yaml.safe_load(data["mas.yaml"])
        matches = [provider for provider in config["upstream_oauth2"]["providers"]
                   if provider.get("issuer", "").rstrip("/") == ISSUER]
        if len(matches) != 1:
            raise ValueError("ambiguous Matrix upstream identity; diagnostics suppressed")
        for field in ("id", "secret"):
            matches[0]["client_" + field] = current["matrix_client_" + field]
        data["mas.yaml"] = yaml.safe_dump(config, sort_keys=False)
    return change


def updates(current):
    """Consumer file -> [(Secret name, change)]; other keys are left untouched."""
    media = {}
    for app in ("sftpgo", "navidrome", "audiomuse"):
        media.update(client(current, app, app.upper() + "_OIDC_CLIENT_", str.upper))
    return {
        "deployments/homelab/cluster/apps/forge/runtime.sops.yaml": [
            ("forge-runtime", lambda data: data.update(client(current, "forgejo", "forgejo-oidc-client-")))],
        "deployments/homelab/cluster/apps/matrix/runtime.sops.yaml": [
            ("matrix-runtime", set_matrix_upstream(current))],
        "deployments/homelab/cluster/apps/media/runtime.sops.yaml": [
            ("media-runtime", lambda data: data.update(media))],
        "deployments/homelab/cluster/infrastructure/observability/runtime.sops.yaml": [
            ("grafana-oidc", lambda data: data.update(
                client(current, "grafana", "GF_AUTH_GENERIC_OAUTH_CLIENT_", str.upper)))],
    }


def render(root, outputs):
    current = identity_values(outputs)
    # Prepare every file before writing any, so a failure changes nothing.
    rendered = {}
    for path, changes in updates(current).items():
        rendered[path] = decrypt(root / path)
        for name, change in changes:
            update_document(rendered[path], name, change)
    return [path for path, documents in rendered.items() if save(root, path, documents)]


def main():
    if len(sys.argv) > 1:
        raise SystemExit(__doc__)
    for path in render(Path.cwd(), json.load(sys.stdin)):
        print("Updated encrypted " + path)


if __name__ == "__main__":
    os.umask(0o077)
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        raise SystemExit("Identity credential update failed; check identity outputs and SOPS access. "
                         "Credential diagnostics suppressed.") from None

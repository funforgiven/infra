#!/usr/bin/env python3
"""Export only retained gateway TLS/account Secrets to a private, one-time bundle.

Offline only: no Kubernetes or provider API calls. Decryption stays in memory;
the requested output is explicitly a private execution artifact outside Git.
"""
import argparse
import base64
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess

import yaml

from encrypted_inputs import decrypt


def openssl(arguments, data):
    try:
        result = subprocess.run(
            ["openssl", *arguments], input=data, capture_output=True, check=True
        )
    except subprocess.CalledProcessError:
        raise ValueError("OpenSSL validation failed; diagnostics suppressed") from None
    return result.stdout


def certificate_definitions(root):
    directory = root / "deployments/homelab/cluster/infrastructure/gateway"
    result = {}
    for filename in ("management.yaml", "gateway.yaml", "public.yaml"):
        for document in yaml.safe_load_all((directory / filename).read_text()):
            if document and document.get("kind") == "Certificate":
                key = (document["metadata"]["namespace"], document["spec"]["secretName"])
                if key in result:
                    raise ValueError("duplicate target certificate")
                result[key] = document
    return result


def render(snapshot, plan, root):
    definitions = certificate_definitions(root)
    sources = {}
    for entry in snapshot["objects"]:
        document = entry["object"]
        key = (entry["sourceCluster"], document["metadata"]["namespace"], document["metadata"]["name"])
        if key in sources:
            raise ValueError("duplicate archived identity")
        sources[key] = document
    items = []
    for entry in plan["objects"]:
        if entry["action"] != "seed-once-before-gateway":
            continue
        source_key = (entry["sourceCluster"], entry["namespace"], entry["name"])
        source = sources[source_key]
        target = entry["target"]
        target_key = (target["namespace"], target["name"])
        if source.get("apiVersion") != "v1" or source.get("kind") != "Secret":
            raise ValueError("archived source is not a Secret")
        data = source["data"]
        annotations = {}
        if source.get("type") == "kubernetes.io/tls":
            definition = definitions[target_key]
            certificate = base64.b64decode(data["tls.crt"], validate=True)
            private_key = base64.b64decode(data["tls.key"], validate=True)
            der = openssl(["x509", "-outform", "DER"], certificate)
            if hashlib.sha256(der).hexdigest() != entry["certificateSHA256"]:
                raise ValueError("certificate does not match public capture fingerprint")
            openssl(["x509", "-checkend", "0", "-noout"], certificate)
            public = openssl(["x509", "-pubkey", "-noout"], certificate)
            if public != openssl(["pkey", "-pubout"], private_key):
                raise ValueError("certificate and key do not match")
            for hostname in definition["spec"]["dnsNames"]:
                result = openssl(["x509", "-checkhost", hostname, "-noout"], certificate)
                if b" does match certificate" not in result:
                    raise ValueError("certificate does not cover desired hostname")
            issuer = definition["spec"]["issuerRef"]
            annotations = {
                key: value for key, value in source["metadata"].get("annotations", {}).items()
                if key.startswith("cert-manager.io/")
            }
            annotations.update({
                "cert-manager.io/certificate-name": definition["metadata"]["name"],
                "cert-manager.io/issuer-name": issuer["name"],
                "cert-manager.io/issuer-kind": issuer.get("kind", "Issuer"),
                "cert-manager.io/issuer-group": issuer.get("group", "cert-manager.io"),
            })
        elif target_key == ("cert-manager", "letsencrypt-cloudflare-account"):
            openssl(["pkey", "-pubout"], base64.b64decode(data["tls.key"], validate=True))
        else:
            raise ValueError("unapproved opaque Secret")
        metadata = dict(target)
        if annotations:
            metadata["annotations"] = annotations
        items.append({"apiVersion": "v1", "kind": "Secret", "metadata": metadata,
                      "type": source.get("type", "Opaque"), "data": copy.deepcopy(data)})
    expected = set(definitions) | {("cert-manager", "letsencrypt-cloudflare-account")}
    actual = [(item["metadata"]["namespace"], item["metadata"]["name"]) for item in items]
    if len(actual) != len(expected) or set(actual) != expected:
        raise ValueError("bundle does not contain exactly the approved four Secrets")
    return {"apiVersion": "v1", "kind": "List", "items": items}


def write_private(bundle, output, root):
    if output.resolve().is_relative_to(root.resolve()):
        raise ValueError("execution bundle must be outside the repository")
    output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if output.parent.stat().st_mode & 0o077:
        raise ValueError("output parent must be owner-only")
    payload = yaml.safe_dump(bundle, sort_keys=False).encode()
    descriptor = os.open(output, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
    except BaseException:
        output.unlink(missing_ok=True)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    parser.add_argument("--snapshot", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.repository_root
    snapshot = args.snapshot or root / "secrets/source-certificates-and-state.sops.yaml"
    plan = json.loads((root / "docs/migration/certificate-plan.json").read_text())
    bundle = render(decrypt(snapshot)[0], plan, root)
    write_private(bundle, args.output, root)
    print("Exported four validated retained Secrets to a new owner-only file; no remote calls.")


if __name__ == "__main__":
    os.umask(0o077)
    try:
        main()
    except Exception:
        raise SystemExit("Certificate export failed; check fresh capture/fingerprints, recipient access, expiry/hostnames, and a new private output path. Value-bearing diagnostics suppressed.") from None

"""Offline rendering shared by schema refresh and validation.

Nothing here prints values: failures name only the resource that failed.
"""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import yaml
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "operations"))
from encrypted_inputs import decrypt, values  # noqa: E402
yaml.SafeLoader.add_constructor("tag:yaml.org,2002:value", lambda loader, node: loader.construct_scalar(node))

KUBE_VERSION = "1.36.4"
API_VERSIONS = ("monitoring.coreos.com/v1", "monitoring.coreos.com/v1/ServiceMonitor", "monitoring.coreos.com/v1/PodMonitor")
# Flux stages labelled with this stay suspended in the recovery overlay.
RECOVERY_HOLD = ("homelab.fahrican.com/recovery", "hold")


def key(document):
    return (document["kind"], document["metadata"].get("namespace", ""), document["metadata"]["name"])


def merge(left, right):
    for name, value in right.items():
        if isinstance(value, dict) and isinstance(left.get(name), dict):
            merge(left[name], value)
        else:
            left[name] = value


def verify_vendors(root):
    vendors = json.loads((root / "deployments/homelab/validation/vendors.json").read_text())
    for entry in vendors["files"]:
        if hashlib.sha256((root / entry["file"]).read_bytes()).hexdigest() != entry["localSHA256"]:
            raise ValueError("vendored manifest checksum mismatch: " + entry["file"])
    return vendors


def render(kustomize, path):
    result = subprocess.run([kustomize, "build", "--load-restrictor", "LoadRestrictionsNone", str(path)], capture_output=True)
    if result.returncode:
        raise ValueError("Kustomize build failed: " + str(path))
    return [document for document in yaml.safe_load_all(result.stdout) if document]


def entrypoints(root, kustomize):
    """Yield (relative path, documents) for every Kustomize entrypoint."""
    for path in sorted((root / "deployments/homelab").rglob("kustomization.yaml")):
        if "routeros" in path.parts:
            continue
        yield str(path.parent.relative_to(root)), render(kustomize, path.parent)


def decrypted_objects(root):
    """Decrypt cluster SOPS Secrets and ConfigMaps into memory only."""
    objects = {}
    for path in (root / "deployments/homelab/cluster").rglob("*.sops.yaml"):
        for document in decrypt(path):
            if document.get("kind") in ["Secret", "ConfigMap"]:
                objects[key(document)] = document
    return objects


def release_values(release, objects, decrypted=None):
    """Resolve a HelmRelease's valuesFrom and inline values like Flux does."""
    namespace = release["metadata"]["namespace"]
    name = release["metadata"]["name"]
    config = {}
    for reference in release["spec"].get("valuesFrom", []):
        source = (reference["kind"], namespace, reference["name"])
        document = (decrypted or {}).get(source, objects.get(source))
        if document is None and reference.get("optional"):
            continue
        if document is None:
            raise ValueError("Missing valuesFrom resource for " + name)
        if reference.get("targetPath"):
            raise ValueError("Explicit targetPath support required")
        if document.get("sops") or (document["kind"] == "Secret" and decrypted is None):
            raise ValueError("Use --decrypt to validate encrypted Helm values")
        values_key = reference.get("valuesKey", "values.yaml")
        if document["kind"] == "Secret":
            payload = values(document)[values_key]
        else:
            payload = document["data"][values_key]
        merge(config, yaml.safe_load(payload) or {})
    merge(config, release["spec"].get("values", {}))
    return config


def helm_template(helm, release, chart, config):
    name = release["metadata"]["name"]
    command = [helm, "template", release["spec"].get("releaseName", name), str(chart),
               "--namespace", release["metadata"]["namespace"], "--kube-version", KUBE_VERSION,
               "--include-crds", "--values", "/dev/stdin"]
    for version in API_VERSIONS:
        command += ["--api-versions", version]
    result = subprocess.run(command, input=yaml.safe_dump(config).encode(), capture_output=True)
    if result.returncode:
        raise ValueError("Helm render failed for " + name + "; diagnostics suppressed")
    return [document for document in yaml.safe_load_all(result.stdout) if document]

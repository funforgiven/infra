#!/usr/bin/env python3
"""Write a private database-only bootstrap bundle while Flux app stages stay held.

Offline: render desired manifests, select the one database and its dependencies,
decrypt selected Secrets in memory and export outside Git. Never contact a cluster.
"""
import argparse
import copy
import os
from pathlib import Path
import subprocess

import yaml

from certificate_bundle import write_private
from encrypted_inputs import decrypt


DATABASES = {"matrix": ("matrix", "matrix-postgres"),
             "audiomuse": ("media", "audiomuse-postgres")}


def select(documents, app):
    namespace, name = DATABASES[app]
    objects = {(d["kind"], d["metadata"].get("namespace", ""), d["metadata"]["name"]): d
               for d in documents if d}
    selected = {}

    def include(kind, identifier):
        key = (kind, namespace, identifier)
        if key not in objects:
            raise ValueError("database dependency is missing; diagnostics suppressed")
        selected[key] = copy.deepcopy(objects[key])
        return selected[key]

    include("Service", name)
    database = include("StatefulSet", name)
    pod = database["spec"]["template"]["spec"]
    # Only these two reviewed StatefulSets are valid bootstrap writers. Full
    # Kustomize rendering preserves the image digest and generated script names.
    database["spec"]["replicas"] = 1
    for volume in pod.get("volumes", []):
        if "persistentVolumeClaim" in volume:
            claim = include("PersistentVolumeClaim", volume["persistentVolumeClaim"]["claimName"])
            if claim["spec"].get("volumeName") or claim["spec"].get("selector"):
                raise ValueError("bootstrap claim must use a fresh target storage identity")
        elif "secret" in volume:
            include("Secret", volume["secret"]["secretName"])
        elif "configMap" in volume:
            include("ConfigMap", volume["configMap"]["name"])
    for reference in pod.get("imagePullSecrets", []):
        include("Secret", reference["name"])
    for container in pod.get("initContainers", []) + pod.get("containers", []):
        for environment in container.get("env", []):
            for kind, field in [("Secret", "secretKeyRef"), ("ConfigMap", "configMapKeyRef")]:
                if field in environment.get("valueFrom", {}):
                    include(kind, environment["valueFrom"][field]["name"])
        for reference in container.get("envFrom", []):
            for kind, field in [("Secret", "secretRef"), ("ConfigMap", "configMapRef")]:
                if field in reference:
                    include(kind, reference[field]["name"])
    order = {"PersistentVolumeClaim": 0, "Secret": 1, "ConfigMap": 2, "Service": 3, "StatefulSet": 4}
    return [selected[key] for key in sorted(selected, key=lambda key: (order[key[0]], key))]


def render(root, app, kustomize):
    folder = "matrix" if app == "matrix" else "media"
    directory = root / "deployments/homelab/cluster/apps" / folder
    process = subprocess.run([kustomize, "build", "--load-restrictor", "LoadRestrictionsNone", str(directory)],
                             capture_output=True, check=True)
    selected = select(list(yaml.safe_load_all(process.stdout)), app)
    private = {}
    for path in directory.rglob("*.sops.yaml"):
        for document in decrypt(path):
            if document and document.get("kind") == "Secret":
                key = (document["metadata"]["namespace"], document["metadata"]["name"])
                if key in private:
                    raise ValueError("duplicate private database dependency")
                private[key] = document
    for index, document in enumerate(selected):
        if document["kind"] == "Secret":
            key = (document["metadata"]["namespace"], document["metadata"]["name"])
            if key not in private:
                raise ValueError("selected Secret is not an encrypted repository input")
            selected[index] = copy.deepcopy(private[key])
            selected[index].pop("sops", None)
    return {"apiVersion": "v1", "kind": "List", "items": selected}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", choices=DATABASES)
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    parser.add_argument("--kustomize", default="kustomize")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.repository_root.resolve()
    bundle = render(root, args.database, args.kustomize)
    write_private(bundle, args.output, root)
    print("Exported one database writer and its dependencies to a private bundle; no cluster calls.")


if __name__ == "__main__":
    os.umask(0o077)
    try:
        main()
    except Exception:
        raise SystemExit("Database bootstrap export failed; check encrypted inputs, manifest dependencies and a private nonexistent output path. Diagnostics suppressed.") from None

#!/usr/bin/env python3
"""Restore offsite data into disposable volumes, never start the application."""

import datetime
import json
import os
from pathlib import Path
import ssl
import time
import urllib.error
import urllib.request

credentials = Path("/var/run/secrets/kubernetes.io/serviceaccount")
context = ssl.create_default_context(cafile=str(credentials / "ca.crt"))
base = "https://kubernetes.default.svc"


def api(method, path, body=None, missing_ok=False):
    request = urllib.request.Request(base + path, method=method,
        headers={"Authorization": "Bearer " + (credentials / "token").read_text(),
                 "Content-Type": "application/json"},
        data=json.dumps(body).encode() if body is not None else None)
    try:
        with urllib.request.urlopen(request, context=context, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        if error.code == 404 and missing_ok:
            return None
        raise RuntimeError(f"Kubernetes {method} {path}: HTTP {error.code}") from None


velero = "/apis/velero.io/v1/namespaces/velero"
backup_name = os.environ.get("RESTORE_BACKUP")
if backup_name:
    backup = api("GET", velero + "/backups/" + backup_name)
else:
    backups = api("GET", velero + "/backups?labelSelector=velero.io%2Fschedule-name%3Dservices-daily")["items"]
    eligible = [item for item in backups if item.get("status", {}).get("phase") == "Completed"
                and "forge" in item["spec"].get("includedNamespaces", [])]
    if not eligible:
        raise RuntimeError("No completed daily backup containing Forgejo exists")
    backup = max(eligible, key=lambda item: item["metadata"]["creationTimestamp"])
    backup_name = backup["metadata"]["name"]
if backup["status"]["phase"] != "Completed" or "forge" not in backup["spec"]["includedNamespaces"]:
    raise RuntimeError("Selected backup is incomplete or does not contain Forgejo")
completed = datetime.datetime.fromisoformat(backup["status"]["completionTimestamp"])
if (datetime.datetime.now(datetime.UTC) - completed).total_seconds() > 93600:
    raise RuntimeError("Selected backup is older than 26 hours")

target = "/api/v1/namespaces/forge-restore/"
for resource in ["pods/forgejo-0", "persistentvolumeclaims/forgejo-data", "persistentvolumeclaims/forgejo-backups"]:
    api("DELETE", target + resource, {"propagationPolicy": "Foreground"}, missing_ok=True)
    deadline = time.monotonic() + 300
    while api("GET", target + resource, missing_ok=True):
        if time.monotonic() > deadline:
            raise TimeoutError("Previous qualification volume or pod is still terminating")
        time.sleep(5)

name = "forge-qualification-" + datetime.datetime.now(datetime.UTC).strftime("%Y%m%d%H%M%S")
api("POST", velero + "/restores", {
    "apiVersion": "velero.io/v1", "kind": "Restore",
    "metadata": {"name": name, "namespace": "velero",
                 "labels": {"backup.fahrican.com/qualification": "true"}},
    "spec": {"backupName": backup_name, "includedNamespaces": ["forge"],
             "includedResources": ["pods", "persistentvolumeclaims"],
             "includeClusterResources": False, "namespaceMapping": {"forge": "forge-restore"},
             "restorePVs": True,
             "resourceModifier": {"kind": "ConfigMap", "name": "forge-restore-modifiers"}},
})
print(f"Checking offsite backup {backup_name} using restore {name}", flush=True)
deadline = time.monotonic() + 3600
while time.monotonic() < deadline:
    phase = api("GET", velero + "/restores/" + name).get("status", {}).get("phase")
    if phase in ("Failed", "PartiallyFailed", "FailedValidation"):
        raise RuntimeError(f"Offsite restore entered {phase}")
    pod = api("GET", target + "pods/forgejo-0", missing_ok=True)
    if phase == "Completed" and pod:
        if any(item["type"] == "Ready" and item["status"] == "True"
               for item in pod.get("status", {}).get("conditions", [])):
            print("Offsite recovery qualified: database, Git, identity and Actions artifact.", flush=True)
            break
    time.sleep(10)
else:
    raise TimeoutError("Offsite restore or data verification did not finish within one hour")

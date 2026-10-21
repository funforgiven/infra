#!/usr/bin/env python3
"""Restore offsite data into disposable volumes, never start the application."""

import datetime
import os
import time
from cluster_http import Kubernetes
from restore_cleanup import cleanup

api = Kubernetes().request


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


cleanup(api)

name = "forge-qualification-" + datetime.datetime.now(datetime.UTC).strftime("%Y%m%d%H%M%S")
api("POST", velero + "/restores", {
    "apiVersion": "velero.io/v1", "kind": "Restore",
    "metadata": {"name": name, "namespace": "velero",
                 "labels": {"backup.fahrican.com/qualification": "true"}},
    "spec": {"backupName": backup_name, "includedNamespaces": ["forge"],
             # Velero 1.18 gates even file-system restores on PV inclusion.
             # Cluster resources stay excluded and PVC modifiers force fresh
             # dynamic provisioning; source PVs are never rebound.
             "includedResources": ["pods", "persistentvolumeclaims", "persistentvolumes"],
             "includeClusterResources": False, "namespaceMapping": {"forge": "forge-restore"},
             "restorePVs": True,
             "resourceModifier": {"kind": "ConfigMap", "name": "forge-restore-modifiers"}},
})
print(f"Checking offsite backup {backup_name} using restore {name}", flush=True)
deadline = time.monotonic() + 14400
while time.monotonic() < deadline:
    phase = api("GET", velero + "/restores/" + name).get("status", {}).get("phase")
    if phase in ("Failed", "PartiallyFailed", "FailedValidation"):
        raise RuntimeError(f"Offsite restore entered {phase}")
    pod = api("GET", target + "pods/forgejo-0", missing=True)
    if phase == "Completed" and pod:
        if any(item["type"] == "Ready" and item["status"] == "True"
               for item in pod.get("status", {}).get("conditions", [])):
            print("Offsite recovery qualified: database, Git, identity and Actions artifact.", flush=True)
            break
    time.sleep(10)
else:
    raise TimeoutError("Offsite restore or data verification did not finish within four hours")

# Preserve failed restores for investigation; successful checks need only the
# controller log and Velero Restore record, not months of scratch storage.
cleanup(api)
print("Disposable restore pod and volumes removed.", flush=True)

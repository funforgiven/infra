#!/usr/bin/env python3
"""Monthly restore drill.

Restore the volumes of the newest daily backup into the deny-all
<namespace>-restore namespaces, run every verifier CronJob declared there,
then delete the copies. Velero restores only PVCs: no workload ever starts.
"""

import datetime
import json
import subprocess
import time

# Must match the namespaces in schedules.yaml.
NAMESPACES = ["backup-qualification", "forge", "games", "home-automation", "matrix", "media", "services-observability"]
TARGETS = [namespace + "-restore" for namespace in NAMESPACES]
VERIFIERS = "backup.fahrican.com/restore-verifier=true"
DRILL = "backup.fahrican.com/restore-drill"
FAILED = ("Failed", "PartiallyFailed", "FailedValidation")


def kubectl(*args, document=None):
    data = None if document is None else json.dumps(document)
    return subprocess.run(["kubectl", *args], input=data, capture_output=True, check=True, text=True).stdout


def get(*args):
    return json.loads(kubectl("get", *args, "-o", "json"))


def wait(check, seconds, what):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if check():
            return
        time.sleep(15)
    raise TimeoutError(what + " timed out")


def newest_daily_backup():
    now = datetime.datetime.now(datetime.timezone.utc)
    candidates = []
    for backup in get("-n", "velero", "backups.velero.io", "-l", "velero.io/schedule-name=daily")["items"]:
        status = backup.get("status", {})
        if status.get("phase") != "Completed":
            continue
        completed = datetime.datetime.fromisoformat(status["completionTimestamp"].replace("Z", "+00:00"))
        if now - completed < datetime.timedelta(hours=26):
            candidates.append((completed, backup["metadata"]["name"]))
    if not candidates:
        raise RuntimeError("no completed daily backup within 26 hours")
    return max(candidates)[1]


def clean():
    """Delete verifier Jobs and every Velero-restored claim; Delete reclaim frees RBD."""
    for namespace in TARGETS:
        kubectl("-n", namespace, "delete", "jobs", "-l", DRILL, "--ignore-not-found", "--wait=true")
        kubectl("-n", namespace, "delete", "pvc", "-l", "velero.io/restore-name", "--ignore-not-found", "--wait=true")


def retained_volumes():
    return sorted(pv["metadata"]["name"] for pv in get("persistentvolumes")["items"]
                  if pv["spec"].get("claimRef", {}).get("namespace") in TARGETS
                  and pv["spec"].get("persistentVolumeReclaimPolicy") != "Delete")


def restore(backup, name):
    kubectl("create", "-f", "-", document={
        "apiVersion": "velero.io/v1", "kind": "Restore",
        "metadata": {"name": name, "namespace": "velero", "labels": {DRILL: "true"}},
        "spec": {
            "backupName": backup,
            "includedNamespaces": NAMESPACES,
            "namespaceMapping": dict(zip(NAMESPACES, TARGETS)),
            # Velero only restores volume data when PVs are in the resource
            # filter; cluster resources stay excluded, so no source PV returns.
            "includedResources": ["persistentvolumeclaims", "persistentvolumes"],
            "includeClusterResources": False,
            "restorePVs": True,
            "labelSelector": {"matchExpressions": [{"key": DRILL, "operator": "NotIn", "values": ["skip"]}]},
            "resourceModifier": {"kind": "ConfigMap", "name": "restore-drill-modifiers"},
        },
    })

    def done():
        phase = get("-n", "velero", "restores.velero.io", name).get("status", {}).get("phase")
        if phase in FAILED:
            raise RuntimeError("restore " + name + " entered " + phase)
        return phase == "Completed"
    wait(done, 4 * 3600, "restore " + name)


def verify(stamp):
    jobs = []
    for namespace in TARGETS:
        if not get("-n", namespace, "pvc", "-l", "velero.io/restore-name")["items"]:
            raise RuntimeError(namespace + ": nothing was restored")
        cronjobs = [c["metadata"]["name"] for c in get("-n", namespace, "cronjobs", "-l", VERIFIERS)["items"]]
        if not cronjobs:
            raise RuntimeError(namespace + ": no restore verifier is declared")
        for cronjob in cronjobs:
            job = cronjob + "-" + stamp
            # The Job inherits the template's restore-drill label, which clean() uses.
            kubectl("-n", namespace, "create", "job", job, "--from=cronjob/" + cronjob)
            jobs.append((namespace, job))
    results = {}

    def finished():
        for namespace, job in jobs:
            for condition in get("-n", namespace, "job", job).get("status", {}).get("conditions", []):
                if condition["type"] in ("Complete", "Failed") and condition["status"] == "True":
                    results[namespace + "/" + job] = condition["type"]
        return len(results) == len(jobs)
    wait(finished, 2 * 3600, "verifiers")
    failed = sorted(job for job, result in results.items() if result != "Complete")
    for job in failed:
        namespace, name = job.split("/")
        # Matrix's verifier suppresses its own diagnostics; others print paths only.
        print(kubectl("-n", namespace, "logs", "job/" + name, "--all-containers", "--tail=50"), flush=True)
    if failed:
        raise RuntimeError("verifiers failed: " + ", ".join(failed))


def main():
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d%H%M%S")
    backup = newest_daily_backup()
    print("Restoring volumes of backup " + backup, flush=True)
    clean()
    try:
        restore(backup, "drill-" + stamp)
        verify(stamp)
    finally:
        retained = retained_volumes()
        # Never leave copies of restored data, including the relay crypto store.
        clean()
    if retained:
        raise RuntimeError("restored volumes kept a Retain policy; delete them by hand: " + ", ".join(retained))
    print("Restore drill passed for backup " + backup, flush=True)


if __name__ == "__main__":
    main()

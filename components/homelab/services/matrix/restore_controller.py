#!/usr/bin/env python3
"""Restore the newest daily Matrix backup into a namespace with denied networking."""

import datetime
import json
import subprocess
import time
import uuid
from pathlib import Path


def run(argv, data=None):
    return subprocess.run(
        ["kubectl", "--cache-dir", "/tmp/kubecache"] + argv,
        input=data,
        capture_output=True,
        check=True,
    ).stdout


def get(namespace, resource, name=None):
    return json.loads(
        run(
            ["-n", namespace, "get", resource]
            + ([name] if name else [])
            + ["-o", "json"]
        )
    )


def apply(document):
    run(["apply", "-f", "-"], json.dumps(document).encode())


def main():
    # Created before even copying registry authentication or restoring resources.
    apply(
        {
            "apiVersion": "networking.k8s.io/v1",
            "kind": "NetworkPolicy",
            "metadata": {
                "name": "matrix-restore-deny-all",
                "namespace": "matrix-restore",
            },
            "spec": {"podSelector": {}, "policyTypes": ["Ingress", "Egress"]},
        }
    )
    now = datetime.datetime.now(datetime.timezone.utc)
    candidates = []
    for backup in get("velero", "backups.velero.io")["items"]:
        if (
            backup["metadata"].get("labels", {}).get("velero.io/schedule-name")
            != "services-daily"
        ):
            continue
        status = backup.get("status", {})
        if status.get("phase") != "Completed" or "matrix" not in backup["spec"].get(
            "includedNamespaces", []
        ):
            continue
        completed = datetime.datetime.fromisoformat(
            status["completionTimestamp"].replace("Z", "+00:00")
        )
        if now - completed < datetime.timedelta(hours=26):
            candidates.append((completed, backup["metadata"]["name"]))
    if not candidates:
        raise ValueError("no recent completed Matrix backup")
    backup_name = max(candidates)[1]
    # Secrets are captured, copied through stdin, and never printed or stored on disk.
    registry = get("matrix", "secret", "matrix-registry")
    registry["metadata"] = {"name": "matrix-registry", "namespace": "matrix-restore"}
    apply(registry)
    scripts = {
        "apiVersion": "v1",
        "kind": "ConfigMap",
        "metadata": {"name": "matrix-restore-tools", "namespace": "matrix-restore"},
        "data": {"restore.py": Path("/scripts/restore.py").read_text()},
    }
    apply(scripts)
    run(
        [
            "-n",
            "matrix-restore",
            "delete",
            "jobs",
            "-l",
            "matrix.fahrican.com/qualification=true",
            "--ignore-not-found=true",
        ]
    )
    for resource, names in (
        ("pods", ["matrix-postgres-0", "matrix-synapse-0", "matrix-relay-0"]),
        ("pvc", ["matrix-postgres", "matrix-dumps", "matrix-media", "matrix-relay"]),
    ):
        run(
            ["-n", "matrix-restore", "delete", resource]
            + names
            + ["--ignore-not-found=true", "--wait=true"]
        )
    restore_name = "matrix-qualification-" + uuid.uuid4().hex[:12]
    apply(
        {
            "apiVersion": "velero.io/v1",
            "kind": "Restore",
            "metadata": {"name": restore_name, "namespace": "velero"},
            "spec": {
                "backupName": backup_name,
                "includedNamespaces": ["matrix"],
                "namespaceMapping": {"matrix": "matrix-restore"},
                "includedResources": ["pods", "persistentvolumeclaims"],
                "includeClusterResources": False,
                "restorePVs": False,
                "labelSelector": {
                    "matchExpressions": [
                        {
                            "key": "app.kubernetes.io/name",
                            "operator": "In",
                            "values": [
                                "matrix-postgres",
                                "matrix-synapse",
                                "matrix-relay",
                            ],
                        }
                    ]
                },
                "resourceModifier": {
                    "kind": "ConfigMap",
                    "name": "matrix-restore-modifiers",
                },
            },
        }
    )
    deadline = time.monotonic() + 4800
    while time.monotonic() < deadline:
        state = (
            get("velero", "restores.velero.io", restore_name)
            .get("status", {})
            .get("phase")
        )
        if state == "Completed":
            break
        if state in ("Failed", "PartiallyFailed", "FailedValidation"):
            raise ValueError("isolated restore failed")
        time.sleep(10)
    else:
        raise ValueError("isolated restore timed out")
    # All restored sleepers co-locate so RWO attachments are shared safely.
    run(
        [
            "-n",
            "matrix-restore",
            "wait",
            "--for=condition=Ready",
            "pod/matrix-postgres-0",
            "pod/matrix-synapse-0",
            "pod/matrix-relay-0",
            "--timeout=15m",
        ]
    )
    source_pod = get("matrix", "pod", "matrix-synapse-0")
    image = source_pod["spec"]["containers"][0]["image"]
    job = {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {
            "name": restore_name,
            "namespace": "matrix-restore",
            "labels": {"matrix.fahrican.com/qualification": "true"},
        },
        "spec": {
            "backoffLimit": 0,
            "activeDeadlineSeconds": 900,
            "template": {
                "metadata": {
                    "labels": {"matrix.fahrican.com/restore-cohort": "matrix"}
                },
                "spec": {
                    "automountServiceAccountToken": False,
                    "restartPolicy": "Never",
                    "imagePullSecrets": [{"name": "matrix-registry"}],
                    "securityContext": {
                        "fsGroup": 1000,
                        "seccompProfile": {"type": "RuntimeDefault"},
                    },
                    "affinity": {
                        "podAffinity": {
                            "requiredDuringSchedulingIgnoredDuringExecution": [
                                {
                                    "topologyKey": "kubernetes.io/hostname",
                                    "labelSelector": {
                                        "matchLabels": {
                                            "matrix.fahrican.com/restore-cohort": "matrix"
                                        }
                                    },
                                }
                            ]
                        }
                    },
                    "containers": [
                        {
                            "name": "verify",
                            "image": image,
                            "command": ["python", "/scripts/restore.py"],
                            "resources": {
                                "requests": {"cpu": "100m", "memory": "256Mi"},
                                "limits": {"cpu": "1", "memory": "1Gi"},
                            },
                            "securityContext": {
                                "runAsNonRoot": True,
                                "runAsUser": 1000,
                                "runAsGroup": 1000,
                                "allowPrivilegeEscalation": False,
                                "readOnlyRootFilesystem": True,
                                "capabilities": {"drop": ["ALL"]},
                            },
                            "volumeMounts": [
                                {"name": name, "mountPath": path, "readOnly": True}
                                for name, path in (
                                    ("dumps", "/var/lib/matrix/dumps"),
                                    ("media", "/var/lib/matrix/media"),
                                    ("state", "/var/lib/matrix/relay"),
                                    ("scripts", "/scripts"),
                                )
                            ]
                            + [{"name": "tmp", "mountPath": "/tmp"}],
                        }
                    ],
                    "volumes": [
                        {"name": name, "persistentVolumeClaim": {"claimName": claim}}
                        for name, claim in (
                            ("dumps", "matrix-dumps"),
                            ("media", "matrix-media"),
                            ("state", "matrix-relay"),
                        )
                    ]
                    + [
                        {
                            "name": "scripts",
                            "configMap": {"name": "matrix-restore-tools"},
                        },
                        {"name": "tmp", "emptyDir": {}},
                    ],
                },
            },
        },
    }
    apply(job)
    run(
        [
            "-n",
            "matrix-restore",
            "wait",
            "--for=condition=Complete",
            "job/" + restore_name,
            "--timeout=15m",
        ]
    )
    print("Matrix isolated restore qualification completed.")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        raise SystemExit(
            "Matrix isolated restore failed; secret-bearing diagnostics suppressed."
        ) from None

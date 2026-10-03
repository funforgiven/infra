"""Qualify a fresh NetBird backup in a disposable, network-isolated database."""

import copy
import json
import secrets
import subprocess
import time


def kubectl(*args, document=None):
    result = subprocess.run(
        ["kubectl", *args],
        input=None if document is None else json.dumps(document).encode(),
        capture_output=True, check=True,
    )
    return result.stdout


def get(namespace, kind, name):
    return json.loads(kubectl("-n", namespace, "get", kind, name, "-o", "json"))


def create(document):
    kubectl("create", "-f", "-", document=document)


def wait_for(namespace, kind, name, predicate, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        resource = get(namespace, kind, name)
        if predicate(resource):
            return resource
        time.sleep(5)
    raise TimeoutError(f"Timed out waiting for {namespace}/{kind}/{name}")


def sql(namespace, pod, database, query):
    return kubectl(
        "-n", namespace, "exec", pod, "-c", "postgres", "--",
        "psql", "-v", "ON_ERROR_STOP=1", "-At", "-d", database, "-c", query,
    ).decode().strip()


def snapshot(namespace, primary):
    # Compare configuration and key counts, never secret contents or live peer
    # counts (the operator can legitimately replace peers during the check).
    result = {}
    for database, tables in (
        ("netbird", ("accounts", "policies", "groups", "zones", "records")),
        ("netbird_auth", ("connector", "keys")),
    ):
        for table in tables:
            count = int(sql(namespace, primary, database, f'SELECT count(*) FROM "{table}"'))
            if count < 1:
                raise ValueError(f"Missing required state: {database}/{table}")
            result[f"{database}/{table}"] = count
    disabled = sql(namespace, primary, "netbird", "SELECT count(*) = 1 AND NOT bool_or(enabled) FROM policies WHERE name = 'Default'")
    if disabled != "t":
        raise ValueError("The default mesh policy must remain disabled")
    event_tables = sql(namespace, primary, "netbird_events", "SELECT count(*) FROM pg_tables WHERE schemaname = 'public'")
    if int(event_tables) < 1:
        raise ValueError("Missing event database schema")
    return result


def restore_check():
    production = get("netbird", "cluster", "netbird-postgres")
    expected = snapshot("netbird", production["status"]["currentPrimary"])
    suffix = secrets.token_hex(4)
    backup_name = "netbird-qualification-" + suffix
    print(f"Creating production backup {backup_name}", flush=True)
    create({
        "apiVersion": "postgresql.cnpg.io/v1", "kind": "Backup",
        "metadata": {"name": backup_name, "namespace": "netbird"},
        "spec": {
            "cluster": {"name": "netbird-postgres"}, "method": "plugin",
            "online": True, "onlineConfiguration": {"waitForArchive": True},
            "target": "prefer-standby",
            "pluginConfiguration": {"name": "barman-cloud.cloudnative-pg.io"},
        },
    })

    def backup_complete(resource):
        phase = resource.get("status", {}).get("phase")
        if phase == "failed":
            raise RuntimeError("Production backup failed; inspect the Backup resource")
        return phase == "completed"

    backup = wait_for("netbird", "backup", backup_name, backup_complete, 900)
    # Standby base-backup completion can precede primary archival of its last
    # WAL segment. Close that segment and wait for durable archive confirmation
    # before starting recovery, rather than relying on the periodic switch.
    primary = get("netbird", "cluster", "netbird-postgres")["status"]["currentPrimary"]
    end_wal = backup["status"]["endWal"]
    if len(end_wal) != 24 or any(char not in "0123456789ABCDEF" for char in end_wal):
        raise ValueError("Invalid backup WAL metadata")
    sql("netbird", primary, "postgres", "SELECT pg_switch_wal()")
    deadline = time.monotonic() + 300
    while sql("netbird", primary, "postgres", f"SELECT last_archived_wal >= '{end_wal}' FROM pg_stat_archiver") != "t":
        if time.monotonic() > deadline:
            raise TimeoutError("Backup WAL did not reach the recovery archive")
        time.sleep(5)
    namespace = "netbird-restore-" + suffix
    # create (not apply) ensures cleanup can only touch a namespace we own.
    create({
        "apiVersion": "v1", "kind": "Namespace",
        "metadata": {"name": namespace, "labels": {"pod-security.kubernetes.io/enforce": "restricted"}},
    })
    print(f"Restoring into {namespace}; production remains online", flush=True)
    try:
        create({
            "apiVersion": "networking.k8s.io/v1", "kind": "NetworkPolicy",
            "metadata": {"name": "restore-isolation", "namespace": namespace},
            "spec": {
                "podSelector": {}, "policyTypes": ["Ingress", "Egress"],
                "ingress": [{
                    "from": [{"namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": "cnpg-system"}}}],
                    "ports": [{"protocol": "TCP", "port": 8000}],
                }],
                "egress": [],
            },
        })
        # Enforce before Magnum's order-20 global egress Allow. The restored
        # server accepts no application traffic and has no production DB route.
        policy_name = namespace + "-egress"
        create({
            "apiVersion": "crd.projectcalico.org/v1", "kind": "GlobalNetworkPolicy",
            "metadata": {"name": policy_name},
            "spec": {
                "order": 15, "namespaceSelector": f"kubernetes.io/metadata.name == '{namespace}'",
                "selector": "all()", "types": ["Egress"],
                "egress": [
                    {"action": "Allow", "protocol": protocol, "destination": {
                        "namespaceSelector": "kubernetes.io/metadata.name == 'kube-system'",
                        "selector": "k8s-app == 'kube-dns'", "ports": [53],
                    }} for protocol in ("TCP", "UDP")
                ] + [
                    {"action": "Allow", "protocol": "TCP", "destination": {"ports": [443, 6443]}},
                    {"action": "Deny"},
                ],
            },
        })
        secret = get("netbird", "secret", "netbird-backup")
        create({
            "apiVersion": "v1", "kind": "Secret",
            "metadata": {"name": "netbird-backup", "namespace": namespace},
            "type": "Opaque", "data": secret["data"],
        })
        store = get("netbird", "objectstore", "netbird-postgres-backup")
        create({
            "apiVersion": store["apiVersion"], "kind": store["kind"],
            "metadata": {"name": "source", "namespace": namespace},
            "spec": {"configuration": store["spec"]["configuration"]},
        })
        spec = production["spec"]
        restore_spec = {
            "instances": 1, "imageName": spec["imageName"],
            "storage": copy.deepcopy(spec["storage"]), "resources": spec["resources"],
            "bootstrap": {"recovery": {"source": "source"}},
            "externalClusters": [{"name": "source", "plugin": {
                "name": "barman-cloud.cloudnative-pg.io",
                "parameters": {"barmanObjectName": "source", "serverName": "netbird-postgres"},
            }}],
            # Deliberately no spec.plugins: recovery can read the original
            # archive but this cluster must never archive into it.
        }
        create({
            "apiVersion": "postgresql.cnpg.io/v1", "kind": "Cluster",
            "metadata": {"name": "restore", "namespace": namespace}, "spec": restore_spec,
        })
        restored = wait_for(namespace, "cluster", "restore", lambda obj: any(
            condition["type"] == "Ready" and condition["status"] == "True"
            for condition in obj.get("status", {}).get("conditions", [])
        ), 1200)
        actual = snapshot(namespace, restored["status"]["currentPrimary"])
        if actual != expected:
            raise ValueError("Restored configuration counts differ from the pre-backup snapshot")
        print("PASS: configuration, identity connector, signing keys, event schema and disabled mesh policy restored", flush=True)
    finally:
        # Retain the egress boundary until all disposable pods are gone.
        kubectl("delete", "namespace", namespace, "--wait=true", "--timeout=180s")
        kubectl("delete", "globalnetworkpolicy", namespace + "-egress", "--ignore-not-found")
        print(f"Removed disposable namespace {namespace}", flush=True)

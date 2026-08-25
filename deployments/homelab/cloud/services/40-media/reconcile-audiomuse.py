#!/usr/bin/env python3
"""Idempotently reconcile AudioMuse's supported cron API."""

import json
import time
import urllib.error
import urllib.request


BASE = "http://audiomuse-api.media.svc.cluster.local:8000"
DESIRED = {
    "analysis": ("Hourly library analysis", "17 * * * *"),
    "clustering": ("Nightly clustering", "20 3 * * *"),
    "sonic_fingerprint": ("Nightly sonic fingerprints", "40 4 * * *"),
}


def request(method, path, payload=None):
    body = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(
        BASE + path,
        data=body,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.load(response)


for attempt in range(30):
    try:
        request("GET", "/api/health")
        break
    except (OSError, urllib.error.URLError):
        if attempt == 29:
            raise
        time.sleep(2)

entries = request("GET", "/api/cron")
by_type = {entry["task_type"]: entry for entry in entries}

for task_type, (name, expression) in DESIRED.items():
    current = by_type.get(task_type, {})
    if (
        current.get("name") == name
        and current.get("cron_expr") == expression
        and current.get("enabled") is True
        and current.get("options", {}) == {}
    ):
        continue
    payload = {
        "name": name,
        "task_type": task_type,
        "cron_expr": expression,
        "enabled": True,
        "options": {},
    }
    if current.get("id"):
        payload["id"] = current["id"]
    request("POST", "/api/cron", payload)

print("AudioMuse cron policy is reconciled")

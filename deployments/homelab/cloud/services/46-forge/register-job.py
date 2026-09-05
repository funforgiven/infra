#!/usr/bin/env python3
"""Exchange the init-only repository credential for a one-job runner identity."""

import json
import os
from pathlib import Path
import sys
import time
import urllib.request

os.umask(0o077)
repository = os.environ["FORGE_REPOSITORY"]
name = os.environ["POD_NAME"]
base = "https://git.fahrican.com/api/v1/repos/" + repository + "/actions/runners"
token = Path("/run/enrollment/token").read_text().strip()


def request(method, path="", body=None):
    request = urllib.request.Request(base + path, method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": "token " + token, "Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response) if response.status != 204 else None


# Kubernetes expires idle/failed job pods after three hours. Remove only
# older, offline ephemeral identities belonging to this managed CronJob.
for runner in request("GET", "?limit=50"):
    if not runner["ephemeral"] or runner["status"] != "offline":
        continue
    if not runner["name"].startswith("forge-linux-qualification-"):
        continue
    try:
        minute = int(runner["name"].split("-")[-2])
    except ValueError:
        continue
    if time.time() - minute * 60 > 21600:
        request("DELETE", "/" + str(runner["id"]))

jobs = request("GET", "/jobs?labels=linux-x86_64")
waiting = [job for job in jobs if job["status"] == "waiting"
           and set(job["runs_on"]) <= {"linux", "linux-x86_64"}]
if not waiting:
    print("No eligible Linux jobs are waiting.")
    sys.exit(0)
handle = waiting[0]["handle"]
registered = request("POST", body={"name": name, "ephemeral": True,
    "description": "Disposable restricted Kubernetes job; one assignment only"})
root = Path("/run/runner")
(root / "uuid").write_text(registered["uuid"])
(root / "token").write_text(registered["token"])
(root / "handle").write_text(handle)
print("Registered a repository-scoped ephemeral runner; enrollment credential remains in init only.")

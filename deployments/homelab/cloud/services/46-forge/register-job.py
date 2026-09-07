#!/usr/bin/env python3
"""Exchange the init-only repository credential for a one-job runner identity."""

import json
import os
from pathlib import Path
import re
import sys
import time
import urllib.request


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None

def runner_configuration(base, raw_cache, now=None):
    """Copy the immutable configuration, adding only a validated job capability."""
    if not raw_cache:
        return base
    try:
        if len(raw_cache) > 1024:
            raise ValueError()
        cache = json.loads(raw_cache)
        now = time.time() if now is None else now
        if (not isinstance(cache, dict) or set(cache) != {"actions_cache_url", "cache_mode", "expires_unix"}
                or not isinstance(cache.get("actions_cache_url"), str)
                or not re.fullmatch(r"https://cache\.fahrican\.com/[0-9a-f]{64}/", cache["actions_cache_url"])
                or cache.get("cache_mode") != "broker-scoped-v1"
                or type(cache.get("expires_unix")) is not int
                or not now < cache["expires_unix"] <= now + 7200):
            raise ValueError()
        anchor = '  env_file: ""\n'
        if base.count(anchor) != 1:
            raise ValueError()
        envs = {"ACTIONS_CACHE_URL": cache["actions_cache_url"], "FORGE_CACHE_MODE": cache["cache_mode"]}
        return base.replace(anchor, anchor + "  envs: " + json.dumps(envs) + "\n")
    except (ValueError, TypeError):
        print("Optional cache capability unavailable; continuing with a cold job.", flush=True)
        return base


def main():
    os.umask(0o077)
    repository = os.environ["FORGE_REPOSITORY"]
    name = os.environ["POD_NAME"]
    base = "https://git.fahrican.com/api/v1/repos/" + repository + "/actions/runners"
    token = Path("/run/enrollment/token").read_text().strip()


    def request(method, path="", body=None):
        request = urllib.request.Request(base + path, method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Authorization": "token " + token, "Content-Type": "application/json"})
        with urllib.request.build_opener(NoRedirect).open(request, timeout=30) as response:
            return json.load(response) if response.status != 204 else None


    # Kubernetes expires idle/failed job pods after three hours. Remove only
    # older, offline ephemeral identities belonging to this managed CronJob.
    for runner in request("GET", "?limit=50") or []:
        if not runner["ephemeral"] or runner["status"] != "offline":
            continue
        match = re.match(r"^forge-linux-(?:qualification|atollion)-(\d+)-", runner["name"])
        if not match:
            continue
        try:
            minute = int(match.group(1))
        except ValueError:
            continue
        if time.time() - minute * 60 > 21600:
            request("DELETE", "/" + str(runner["id"]))

    jobs = request("GET", "/jobs?labels=linux-x86_64") or []
    waiting = [job for job in jobs if job["status"] == "waiting"
               and job["runs_on"] and set(job["runs_on"]) <= {"linux", "linux-x86_64"}]
    if os.environ.get("FORGE_JOB_HANDLE"):
        waiting = [job for job in waiting if job["handle"] == os.environ["FORGE_JOB_HANDLE"]]
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
    (root / "runner.yaml").write_text(runner_configuration(
        Path("/bootstrap/runner.yaml").read_text(), os.environ.get("FORGE_CACHE_CONFIG")))
    print("Registered a repository-scoped ephemeral runner; enrollment credential remains in init only.")


if __name__ == "__main__":
    main()

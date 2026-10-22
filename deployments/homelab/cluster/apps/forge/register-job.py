#!/usr/bin/env python3
"""Exchange the init-only repository credential for a one-job runner identity."""

from http.client import IncompleteRead
import json
import os
from pathlib import Path
import re
import ssl
import sys
import time
import urllib.error
import urllib.request

from cluster_http import NoRedirect

PAGE_SIZE = 50
# Runner Jobs end within activeDeadlineSeconds (2.5h); an offline identity
# whose name minute is older than this can never be used again.
STALE_SECONDS = 6 * 3600


def registration_request(opener, request, deadline):
    """Wait out short maintenance pauses without replaying enrollment writes."""
    readable = request.get_method() == "GET"
    while True:
        remaining = deadline - time.monotonic()
        if readable and remaining <= 0:
            raise TimeoutError("Forgejo registration read recovery deadline expired")
        try:
            with opener.open(request, timeout=min(30, remaining) if readable else 30) as response:
                return json.load(response) if response.status != 204 else None
        except urllib.error.HTTPError as error:
            if not readable or error.code not in {502, 503, 504}:
                raise
            error.close()
        except (urllib.error.URLError, TimeoutError, ConnectionError, IncompleteRead) as error:
            if not readable or isinstance(getattr(error, "reason", error), ssl.SSLError):
                raise
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("Forgejo registration read recovery deadline expired")
        time.sleep(min(5, remaining))


def stale_runners(runners, now):
    """Offline ephemeral identities created by these CronJobs and long expired."""
    for runner in runners:
        if not runner["ephemeral"] or runner["status"] != "offline":
            continue
        match = re.match(r"^forge-linux-(?:qualification|atollion)-(\d+)-", runner["name"])
        if match and now - int(match.group(1)) * 60 > STALE_SECONDS:
            yield runner["id"]


def cache_environment(raw_cache, now=None):
    """Return the runner env_file contents for a validated job cache capability."""
    if not raw_cache:
        return ""
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
        return ("ACTIONS_CACHE_URL=" + cache["actions_cache_url"] + "\n"
                "FORGE_CACHE_MODE=" + cache["cache_mode"] + "\n")
    except (ValueError, TypeError):
        print("Optional cache capability unavailable; continuing with a cold job.", flush=True)
        return ""


def main():
    os.umask(0o077)
    repository = os.environ["FORGE_REPOSITORY"]
    name = os.environ["POD_NAME"]
    base = "https://git.fahrican.com/api/v1/repos/" + repository + "/actions/runners"
    token = Path("/run/enrollment/token").read_text().strip()
    opener = urllib.request.build_opener(NoRedirect)
    # One budget covers every discovery read, including response bodies.
    # POST/DELETE are attempted once; uncertain writes are never replayed.
    deadline = time.monotonic() + 180


    def request(method, path="", body=None):
        request = urllib.request.Request(base + path, method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Authorization": "token " + token, "Content-Type": "application/json"})
        return registration_request(opener, request, deadline)


    runners, page = [], 1
    while True:
        batch = request("GET", f"?limit={PAGE_SIZE}&page={page}") or []
        runners += batch
        if len(batch) < PAGE_SIZE:
            break
        page += 1
    for identity in stale_runners(runners, time.time()):
        request("DELETE", "/" + str(identity))

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
    # runner.yaml names this file as env_file; it is always written so a cold
    # job never reads a stale or missing capability.
    (root / "env").write_text(cache_environment(os.environ.get("FORGE_CACHE_CONFIG")))
    print("Registered a repository-scoped ephemeral runner; enrollment credential remains in init only.")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Create at most two disposable Atollion jobs; never execute repository code."""

import copy
import json
from pathlib import Path
import ssl
import time
import urllib.error
import urllib.request

REPOSITORY = "funforgiven/atollion"
JOBS = "/apis/batch/v1/namespaces/forge-ci/jobs"
LABEL = "forge.fahrican.com/repository=atollion"
CAPACITY = 2


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def request(method, url, token, body=None, context=None):
    req = urllib.request.Request(url, method=method,
        headers={"Authorization": "Bearer " + token.strip(), "Content-Type": "application/json"},
        data=json.dumps(body).encode() if body is not None else None)
    try:
        opener = urllib.request.build_opener(NoRedirect, urllib.request.HTTPSHandler(context=context))
        with opener.open(req, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"Launcher {method}: HTTP {error.code}") from None


def select_jobs(existing, waiting):
    active = [job for job in existing if not any(
        condition.get("status") == "True" and condition.get("type") in {"Complete", "Failed"}
        for condition in job.get("status", {}).get("conditions", []))]
    claimed = {job["metadata"].get("annotations", {}).get("forge.fahrican.com/job-id") for job in existing}
    eligible = [job for job in waiting if job.get("status") == "waiting" and job.get("runs_on")
        and set(job["runs_on"]) <= {"linux", "linux-x86_64"} and str(job["id"]) not in claimed]
    return sorted(eligible, key=lambda job: job["id"])[:max(0, CAPACITY - len(active))]


def main():
    credentials = Path("/var/run/secrets/kubernetes.io/serviceaccount")
    context = ssl.create_default_context(cafile=str(credentials / "ca.crt"))
    kube_token = (credentials / "token").read_text()
    def kube(method, path, body=None):
        return request(method, "https://kubernetes.default.svc" + path, kube_token, body, context)
    existing = kube("GET", JOBS + "?labelSelector=" + LABEL)["items"]
    waiting = request("GET", "https://git.fahrican.com/api/v1/repos/" + REPOSITORY
                      + "/actions/runners/jobs?labels=linux-x86_64", Path("/run/enrollment/token").read_text())
    # Kustomize rewrites this suspended template's ConfigMap references. Read
    # the reconciled spec so newly created jobs use the exact deployed scripts.
    suspended = kube("GET", "/apis/batch/v1/namespaces/forge-ci/cronjobs/forge-linux-atollion-template")
    if suspended["spec"].get("suspend") is not True:
        raise RuntimeError("The Atollion job template must remain suspended")
    template = {"apiVersion": "batch/v1", "kind": "Job",
                "metadata": {"namespace": "forge-ci", "labels": {"forge.fahrican.com/repository": "atollion",
                             "app.kubernetes.io/name": "forge-runner"}},
                "spec": suspended["spec"]["jobTemplate"]["spec"]}
    for assignment in select_jobs(existing, waiting or []):
        job = copy.deepcopy(template)
        job["metadata"]["name"] = "forge-linux-atollion-" + str(int(time.time() // 60)) + "-" + str(assignment["id"])
        job["metadata"]["annotations"] = {"forge.fahrican.com/job-id": str(assignment["id"])}
        job["spec"]["template"]["spec"]["initContainers"][0]["env"].append(
            {"name": "FORGE_JOB_HANDLE", "value": assignment["handle"]})
        kube("POST", JOBS, job)
        print("Created disposable Atollion Linux job", assignment["id"], flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(str(error) if isinstance(error, RuntimeError) else type(error).__name__)
        raise SystemExit(1) from None

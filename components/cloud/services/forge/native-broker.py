#!/usr/bin/env python3
"""Launch one repository-scoped native job; never run repository code here.

The Kubernetes CronJob uses concurrencyPolicy=Forbid. Windows additionally has
one pre-created Neutron port, so Nova enforces exclusivity across controllers.
Only the ephemeral Forgejo identity is put on a fresh guest's config drive.
"""

import argparse
import base64
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

FORGE = "https://git.fahrican.com/api/v1"
IDENTITY = "https://identity.cloud.fahrican.com/v3"
COMPUTE = "https://compute.cloud.fahrican.com/v2.1"
IMAGE = "https://image.cloud.fahrican.com/v2"
VOLUME = "https://volume.cloud.fahrican.com/v3"
MANAGER = "forge-native-broker-v1"
PREFIX = "forge-windows-job-"
DEADLINE = 8100


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def request(method, url, headers=None, body=None, missing=False):
    req = urllib.request.Request(url, method=method,
        headers={"Content-Type": "application/json", **(headers or {})},
        data=json.dumps(body).encode() if body is not None else None)
    try:
        with urllib.request.build_opener(NoRedirect).open(req, timeout=45) as response:
            raw = response.read()
            return (json.loads(raw) if raw else None), response.headers
    except urllib.error.HTTPError as error:
        if missing and error.code == 404:
            return None, error.headers
        # Never include secret-bearing request bodies or remote error details.
        raise RuntimeError(f"{method} {urllib.parse.urlsplit(url).path}: HTTP {error.code}") from None


class Forge:
    def __init__(self, repository, token, platform="windows"):
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
            raise ValueError("Invalid repository")
        self.base = FORGE + "/repos/" + repository + "/actions/runners"
        self.headers = {"Authorization": "token " + token.strip()}
        if platform not in {"windows", "macos"}:
            raise ValueError("Unsupported native platform")
        self.platform = platform
        self.prefix = "forge-" + platform + "-job-"

    def call(self, method, suffix="", body=None, missing=False):
        return request(method, self.base + suffix, self.headers, body, missing)[0]

    def waiting(self):
        return [job for job in self.call("GET", "/jobs?labels=" + self.platform + "-x86_64") or []
                if job["status"] == "waiting" and job["runs_on"]
                and set(job["runs_on"]) <= {self.platform, self.platform + "-x86_64"}]

    def reap(self):
        for runner in self.call("GET", "?limit=100") or []:
            if not (runner["ephemeral"] and runner["status"] == "offline" and runner["name"].startswith(self.prefix)):
                continue
            try:
                created = int(runner["name"][len(self.prefix):].split("-")[0])
            except ValueError:
                continue
            if time.time() - created > DEADLINE + 600:
                self.call("DELETE", "/" + str(runner["id"]), missing=True)


class Cloud:
    def __init__(self, credential, project):
        self.credential, self.project = credential, project
        self.headers, self.renew_at = {}, 0

    def call(self, method, base, path, body=None, missing=False):
        if time.monotonic() >= self.renew_at:
            auth, headers = request("POST", IDENTITY + "/auth/tokens", body={"auth": {
                "identity": {"methods": ["application_credential"], "application_credential": self.credential}}})
            if auth["token"]["project"]["id"] != self.project:
                raise RuntimeError("Cloud credential is scoped to the wrong project")
            roles = {role["name"] for role in auth["token"]["roles"]}
            if "admin" in roles or "member" not in roles:
                raise RuntimeError("Broker requires a non-administrator project member credential")
            self.headers = {"X-Auth-Token": headers["X-Subject-Token"]}
            self.renew_at = time.monotonic() + 600
        headers = dict(self.headers)
        if base == COMPUTE:
            headers["OpenStack-API-Version"] = "compute 2.90"
        elif base == VOLUME:
            headers["OpenStack-API-Version"] = "volume 3.1"
        return request(method, base + path, headers, body, missing)[0]

    def owned(self, server):
        return (server["name"].startswith(PREFIX)
                and server["metadata"].get("managed_by") == MANAGER
                and server["tenant_id"] == self.project)

    def remove(self, server):
        if not self.owned(server):
            raise RuntimeError("Refusing to delete a VM outside broker ownership")
        attachments = self.call("GET", COMPUTE, "/servers/" + server["id"] + "/os-volume_attachments", missing=True)
        volumes = (attachments or {}).get("volumeAttachments", [])
        if any(volume.get("delete_on_termination") is not True for volume in volumes):
            raise RuntimeError("Refusing to delete a VM with an unexpected retained disk")
        self.call("DELETE", COMPUTE, "/servers/" + server["id"], missing=True)
        for _ in range(60):
            vm_gone = self.call("GET", COMPUTE, "/servers/" + server["id"], missing=True) is None
            disks_gone = all(self.call("GET", VOLUME, "/" + self.project + "/volumes/" + volume["volumeId"], missing=True) is None for volume in volumes)
            if vm_gone and disks_gone:
                print("Verified deletion of the disposable Windows VM and its attached job disks.", flush=True)
                return
            time.sleep(5)
        raise RuntimeError("Disposable Windows VM deletion did not finish")

    def reap(self):
        # No all_tenants option: the credential cannot enumerate other projects.
        servers = self.call("GET", COMPUTE, "/servers/detail")["servers"]
        for server in servers:
            if not self.owned(server):
                continue
            expires = int(server["metadata"].get("expires_unix", "0"))
            if not expires or expires <= time.time() or server["status"] in {"ERROR", "SHUTOFF"}:
                self.remove(server)
            else:
                raise RuntimeError("A managed Windows job is still active")
        volumes = self.call("GET", VOLUME, "/" + self.project + "/volumes/detail")["volumes"]
        for volume in volumes:
            if self.owned_volume(volume):
                if int(volume["metadata"].get("expires_unix", "0")) > time.time():
                    raise RuntimeError("A managed Windows job disk is still being prepared")
                self.remove_volume(volume["id"])

    def owned_volume(self, volume):
        return (volume.get("name", "").startswith(PREFIX)
                and volume.get("metadata", {}).get("managed_by") == MANAGER
                and volume["metadata"].get("forge_project_id") == self.project)

    def remove_volume(self, identity):
        path = "/" + self.project + "/volumes/" + identity
        current = self.call("GET", VOLUME, path, missing=True)
        if current is None:
            return
        volume = current["volume"]
        if not self.owned_volume(volume) or volume.get("attachments"):
            raise RuntimeError("Refusing to delete an unowned or attached preparation disk")
        self.call("DELETE", VOLUME, path)
        for _ in range(60):
            if self.call("GET", VOLUME, path, missing=True) is None:
                print("Verified deletion of the Windows preparation disk.", flush=True)
                return
            time.sleep(5)
        raise RuntimeError("Windows preparation disk deletion did not finish")

    def prepare_volume(self, identity):
        # Nova's default image-to-volume wait is only three minutes. Prepare
        # this large desktop disk before Nova attaches it, without changing
        # shared compute-service timeouts.
        deadline = time.monotonic() + 1800
        while time.monotonic() < deadline:
            volume = self.call("GET", VOLUME, "/" + self.project + "/volumes/" + identity)["volume"]
            if not self.owned_volume(volume) or volume.get("attachments"):
                raise RuntimeError("Preparation disk ownership or attachment changed")
            if volume["status"] == "available":
                return
            if volume["status"].startswith("error"):
                raise RuntimeError("Windows job disk preparation failed")
            time.sleep(15)
        raise RuntimeError("Windows job disk preparation exceeded thirty minutes")


def run_macos(config, secret_dir, forge):
    forge.reap()
    jobs = forge.waiting()
    if not jobs:
        print("No eligible macOS job is waiting.")
        return
    name = forge.prefix + str(int(time.time())) + "-" + uuid.uuid4().hex[:8]
    registered = forge.call("POST", body={"name": name, "ephemeral": True,
        "description": "Fresh macOS disk overlay; rootless Quickemu; unprivileged single job"})
    try:
        enrollment = {"uuid": registered["uuid"], "token": registered["token"], "handle": jobs[0]["handle"]}
        with tempfile.TemporaryDirectory(prefix="forge-broker-key-") as directory:
            key = Path(directory) / "id_ed25519"
            key.write_bytes((secret_dir / "ssh-key").read_bytes())
            key.chmod(0o600)
            subprocess.run(["ssh", "-T", "-i", str(key), "-o", "BatchMode=yes", "-o", "IdentitiesOnly=yes",
                "-o", "StrictHostKeyChecking=yes", "-o", "UserKnownHostsFile=" + config["macos_known_hosts"],
                "-o", "ForwardAgent=no", "-o", "ClearAllForwardings=yes", "-o", "ConnectTimeout=10",
                "-o", "ServerAliveInterval=30", "-o", "ServerAliveCountMax=3", "forge-broker@10.21.40.126"],
                input=json.dumps(enrollment).encode(), check=True, timeout=DEADLINE + 120)
    finally:
        forge.call("DELETE", "/" + str(registered["id"]), missing=True)


def run(config, secret_dir):
    os.umask(0o077)
    repository = config["repository"]
    if config.get("qualification_only", True) and repository != "forge-runner/runner-qualification":
        raise RuntimeError("Native qualification must finish before enrolling application repositories")
    forge = Forge(repository, (secret_dir / "forge-token").read_text(), config.get("platform", "windows"))
    if forge.platform == "macos":
        return run_macos(config, secret_dir, forge)
    cloud = Cloud(json.loads((secret_dir / "cloud-credential.json").read_text()), config["project_id"])
    cloud.reap()
    forge.reap()
    jobs = forge.waiting()
    if not jobs:
        print("No eligible Windows job is waiting.")
        return
    golden = cloud.call("GET", IMAGE, "/images/" + config["windows_image_id"])
    if not (golden["status"] == "active" and golden["protected"] and golden["visibility"] == "private"
            and golden["owner"] == config["project_id"] and golden.get("image_role") == "forge-windows"
            and golden.get("image_source_revision") == config["windows_image_revision"]):
        raise RuntimeError("Windows golden image does not match the promoted protected image")
    name = PREFIX + str(int(time.time())) + "-" + uuid.uuid4().hex[:8]
    registered, server, volume = None, None, None
    try:
        volume = cloud.call("POST", VOLUME, "/" + cloud.project + "/volumes", {"volume": {
            "name": name, "size": 240, "imageRef": golden["id"],
            "metadata": {"managed_by": MANAGER, "forge_project_id": cloud.project,
                         "expires_unix": str(int(time.time()) + DEADLINE)}}})["volume"]
        print("Preparing a fresh Windows job disk", volume["id"], flush=True)
        cloud.prepare_volume(volume["id"])
        registered = forge.call("POST", body={"name": name, "ephemeral": True,
            "description": "Fresh Windows 11 desktop VM; unprivileged single job; externally expired"})
        enrollment = base64.b64encode(json.dumps({"uuid": registered["uuid"], "token": registered["token"],
            "handle": jobs[0]["handle"]}).encode()).decode()
        userdata = "#ps1_sysnative\n& 'C:\\Forge\\Start-Job.ps1' -EnrollmentBase64 '" + enrollment + "'\nexit $LASTEXITCODE\n"
        created = cloud.call("POST", COMPUTE, "/servers", {"server": {
            "name": name, "flavorRef": config["windows_flavor_id"], "config_drive": True,
            "networks": [{"port": config["windows_port_id"]}],
            "user_data": base64.b64encode(userdata.encode()).decode(),
            "metadata": {"managed_by": MANAGER, "expires_unix": str(int(time.time()) + DEADLINE),
                "forge_repository": repository, "forge_runner_id": str(registered["id"])},
            "block_device_mapping_v2": [{"uuid": volume["id"], "source_type": "volume",
                "destination_type": "volume", "boot_index": 0,
                "delete_on_termination": True}]}})["server"]
        # Retrieve authoritative ownership fields before any cleanup operation.
        server = cloud.call("GET", COMPUTE, "/servers/" + created["id"])["server"]
        print("Created fresh Windows VM", server["id"], "for qualification job", jobs[0]["id"], flush=True)
        end = time.monotonic() + DEADLINE
        while time.monotonic() < end:
            current = cloud.call("GET", COMPUTE, "/servers/" + server["id"], missing=True)
            if current is None:
                raise RuntimeError("Windows job VM disappeared unexpectedly")
            server = current["server"]
            if server["status"] == "ERROR":
                raise RuntimeError("Windows job VM entered ERROR")
            if server["status"] == "SHUTOFF":
                print("Windows job VM shut down; disposing its writable state.", flush=True)
                return
            time.sleep(15)
        raise RuntimeError("Windows job exceeded its external deadline")
    finally:
        try:
            if server is not None:
                cloud.remove(server)
            if volume is not None:
                cloud.remove_volume(volume["id"])
        finally:
            if registered is not None:
                forge.call("DELETE", "/" + str(registered["id"]), missing=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--secret-directory", type=Path, default=Path("/run/broker"))
    args = parser.parse_args()
    def stop(_signum, _frame):
        raise InterruptedError("Broker received termination; cleaning up")
    signal.signal(signal.SIGTERM, stop)
    run(json.loads(args.config.read_text()), args.secret_directory)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        # Error classes and our fixed messages are safe; third-party exception
        # payloads may contain URLs or credentials and must not enter pod logs.
        print("Native broker failed:", str(error) if isinstance(error, (RuntimeError, InterruptedError)) else type(error).__name__, file=sys.stderr)
        raise SystemExit(1) from None

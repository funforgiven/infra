#!/usr/bin/env python3
"""Use the documented homelab access path without persistent kubeconfig files."""

import argparse
import base64
import os
import subprocess
import tempfile
from pathlib import Path

import yaml


def capture(command, timeout=120, **kwargs):
    return subprocess.run(
        command, capture_output=True, check=True, timeout=timeout, **kwargs
    ).stdout


def undercloud_config():
    # Inventory-pinned host identities and the existing sops-nix automation key.
    command = [
        "ssh",
        "-F",
        "/dev/null",
        "-i",
        "/run/secrets/github-ssh-key",
        "-o",
        "IdentitiesOnly=yes",
        "-o",
        "IdentityAgent=none",
        "-o",
        "UserKnownHostsFile=/dev/null",
        "-o",
        "GlobalKnownHostsFile=/etc/ssh/ssh_known_hosts",
        "-o",
        "StrictHostKeyChecking=yes",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=8",
        "ubuntu@10.21.20.10",
        "sudo -S -p '' cat /etc/kubernetes/admin.conf",
    ]
    password = (
        Path("/run/secrets/cloud-host-pecorino-ubuntu-console-password")
        .read_bytes()
        .rstrip(b"\n")
        + b"\n"
    )
    document = yaml.safe_load(capture(command, input=password))
    document["clusters"][0]["cluster"]["server"] = "https://10.21.20.128:6443"
    fd = os.memfd_create("homelab-undercloud-config")
    os.write(fd, yaml.safe_dump(document).encode())
    return fd


def execute(cluster, command):
    import json

    fd = undercloud_config()
    try:
        # A parent-owned memfd remains accessible through nested CLI subprocesses.
        config = f"/proc/{os.getpid()}/fd/{fd}"
        with tempfile.TemporaryDirectory(
            prefix="matrix-access-", dir="/dev/shm"
        ) as temporary:
            environment = dict(os.environ)
            if cluster == "services":
                data = json.loads(
                    capture(
                        [
                            "kubectl",
                            "--kubeconfig",
                            config,
                            "--cache-dir",
                            temporary + "/cache",
                            "--request-timeout=30s",
                            "-n",
                            "openstack",
                            "get",
                            "secret",
                            "magnum-keystone-admin",
                            "-o",
                            "json",
                        ]
                    )
                )["data"]
                environment.update(
                    {
                        key: base64.b64decode(value).decode()
                        for key, value in data.items()
                        if key.startswith("OS_")
                    }
                )
                environment.update(
                    OS_PROJECT_NAME="services",
                    OS_PROJECT_DOMAIN_NAME="Default",
                    # The Helm-generated identity uses cluster-only DNS and an
                    # internal catalog; administration from this host uses the
                    # same private gateway as service-image promotion.
                    OS_AUTH_URL="https://identity.cloud.fahrican.com/v3",
                    OS_INTERFACE="public",
                )
                for key in ("OS_PROJECT_ID", "OS_TENANT_ID", "OS_TENANT_NAME"):
                    environment.pop(key, None)
                capture(
                    [
                        "openstack",
                        "coe",
                        "cluster",
                        "config",
                        "services-v1",
                        "--dir",
                        temporary,
                        "--force",
                    ],
                    env=environment,
                )
                config = temporary + "/config"
                # OpenStack credentials belong only to the Magnum access process.
                environment = dict(os.environ)
            environment["KUBECONFIG"] = config
            return subprocess.run(command, env=environment).returncode
    finally:
        os.close(fd)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cluster", choices=("undercloud", "services"))
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("provide a command after the cluster name")
    return execute(args.cluster, command)


if __name__ == "__main__":
    os.umask(0o077)
    try:
        raise SystemExit(main())
    except Exception:
        raise SystemExit(
            "Homelab access failed; check pinned SSH access, private networking and Magnum. Secret diagnostics suppressed."
        ) from None

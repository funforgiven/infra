#!/usr/bin/env python3
"""Run a command with an ephemeral homelab Kubernetes administrator config."""
import argparse
import os
import subprocess
import tempfile
from pathlib import Path
import yaml

def capture(command, timeout=45, **kwargs):
    return subprocess.run(command, capture_output=True, check=True, timeout=timeout, **kwargs).stdout

SERVERS = ("10.21.20.10", "10.21.20.11", "10.21.20.12")

def read_admin_config():
    for index, server in enumerate(SERVERS):
        command = ["ssh", "-F", "/dev/null", "-i", "/run/secrets/github-ssh-key",
                   "-o", "IdentitiesOnly=yes", "-o", "IdentityAgent=none",
                   "-o", "UserKnownHostsFile=/dev/null", "-o", "GlobalKnownHostsFile=/etc/ssh/ssh_known_hosts",
                   "-o", "StrictHostKeyChecking=yes", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8",
                   f"funforgiven@{server}", "sudo -n cat /etc/rancher/k3s/k3s.yaml"]
        try: return capture(command)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            if index == len(SERVERS) - 1: raise

def cluster_config():
    document = yaml.safe_load(read_admin_config())
    document["clusters"][0]["cluster"]["server"] = "https://10.21.20.128:6443"
    fd = os.memfd_create("homelab-kubeconfig")
    try:
        os.write(fd, yaml.safe_dump(document).encode())
    except BaseException:
        os.close(fd)
        raise
    return fd

def execute(cluster, command):
    if cluster != "cluster":
        raise ValueError("only the homelab cluster is configured")
    fd = cluster_config()
    try:
        with tempfile.TemporaryDirectory(prefix="homelab-access-", dir="/dev/shm") as temporary:
            environment = dict(os.environ)
            environment["KUBECONFIG"] = f"/proc/{os.getpid()}/fd/{fd}"
            if Path(command[0]).name == "kubectl":
                command = [command[0], "--cache-dir", temporary + "/discovery", *command[1:]]
            return subprocess.run(command, env=environment).returncode
    finally:
        os.close(fd)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cluster", choices=("cluster",))
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command: parser.error("provide a command after cluster")
    return execute(args.cluster, command)

if __name__ == "__main__":
    os.umask(0o077)
    try: raise SystemExit(main())
    except Exception: raise SystemExit("Homelab access failed; check pinned SSH access and cluster networking. Credential diagnostics suppressed.") from None

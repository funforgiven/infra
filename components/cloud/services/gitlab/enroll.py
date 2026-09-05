#!/usr/bin/env python3
"""Enroll stateful GitLab backend credentials over pinned SSH without logging them."""
import argparse
import base64
import json
from pathlib import Path
import re
import subprocess


def run(argv, *, data=None):
    return subprocess.run(argv, input=data, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, check=True).stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", help="Pinned SSH target of the GitLab data VM")
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    args = parser.parse_args()
    if not re.fullmatch(r"[a-zA-Z0-9_@.:-]+", args.target) or args.target.startswith("-"):
        parser.error("Invalid SSH target")
    import yaml
    secret = yaml.safe_load(run(["sops", "decrypt", str(args.repository /
        "deployments/homelab/cloud/undercloud/86-gitlab/runtime.sops.yaml")]))["stringData"]
    bundle = {name.replace("-", "_"): secret[name] for name in
              ("postgres-password", "redis-password", "gitaly-token", "shell-token")}
    for value in bundle.values():
        if not re.fullmatch(r"[a-f0-9]{64}", value):
            raise ValueError("Invalid backend credential")
    rgw = json.loads(run(["kubectl", "-n", "rook-ceph", "get", "secret",
                         "rook-ceph-object-user-gitlab-gitlab", "-o", "json"]))["data"]
    access, private = [base64.b64decode(rgw[k]).decode() for k in ("AccessKey", "SecretKey")]
    if not all(re.fullmatch(r"[A-Za-z0-9/+_-]+", value) for value in (access, private)):
        raise ValueError("Invalid object storage credential")
    rclone = ("[ceph]\ntype = s3\nprovider = Ceph\nendpoint = https://gitlab-s3.cloud.fahrican.com\n"
              "region = us-east-1\nforce_path_style = true\n"
              f"access_key_id = {access}\nsecret_access_key = {private}\n")
    for filename, content in [("credentials.json", json.dumps(bundle)), ("rclone.conf", rclone)]:
        script = ("sudo install -d -m 0700 /var/lib/gitlab-bootstrap && "
                  f"sudo install -m 0400 /dev/stdin /var/lib/gitlab-bootstrap/{filename}.next && "
                  f"sudo mv /var/lib/gitlab-bootstrap/{filename}.next /var/lib/gitlab-bootstrap/{filename}")
        run(["ssh", "-o", "StrictHostKeyChecking=yes", args.target, script], data=content.encode())
    print("Backend credentials enrolled. Restart docker-gitlab to apply them.")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError:
        raise SystemExit("Enrollment failed; check SOPS, undercloud access and pinned SSH credentials.") from None

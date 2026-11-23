#!/usr/bin/env python3
"""Enroll credentials for an AWS-to-GCP migration without logging or storing their values."""

import argparse
import json
import subprocess
import urllib.parse
import urllib.request


def main(project, profile):
    def gcloud(*args, data=None):
        return subprocess.run(["gcloud", *args, "--project", project], input=data,
                              stdout=subprocess.PIPE, check=True).stdout

    for name in ("admin", "mailbox", "canary", "resend", "backup", "gcs-hmac"):
        target = f"mail-{name}"
        if gcloud("secrets", "versions", "list", target, "--filter=state=ENABLED",
                  "--limit=1", "--format=value(name)").strip():
            continue
        if name == "gcs-hmac":
            owner = f"mail-blobs@{project}.iam.gserviceaccount.com"
            url = (f"https://storage.googleapis.com/storage/v1/projects/{project}/hmacKeys?"
                   + urllib.parse.urlencode({"serviceAccountEmail": owner}))
            token = gcloud("auth", "print-access-token").decode().strip()
            req = urllib.request.Request(url, data=b"", headers={"Authorization": "Bearer " + token})
            with urllib.request.urlopen(req, timeout=30) as response:
                key = json.load(response)
            access_id = key["metadata"]["accessId"]
            value = json.dumps({"accessId": access_id, "secret": key["secret"]}).encode()
        else:
            value = subprocess.check_output([
                "aws", "--region", "eu-central-1", "--profile", profile, "secretsmanager",
                "get-secret-value", "--secret-id", f"fahrican/stalwart/{name}",
                "--query", "SecretString", "--output", "text"]).strip()
        if not value or value == b"None":
            raise ValueError(f"No credential returned for {name}")
        try:
            gcloud("secrets", "versions", "add", target, "--data-file=-", data=value)
        except subprocess.CalledProcessError:
            if name == "gcs-hmac":
                gcloud("storage", "hmac", "update", access_id, "--deactivate")
            raise
        print("Enrolled", target)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--aws-profile", default="default")
    args = parser.parse_args()
    main(args.project, args.aws_profile)

#!/usr/bin/env python3
"""Create a locked project runner and write its one-time token to a private file."""

import argparse
import json
import os
from pathlib import Path
import re
import urllib.error
import urllib.request


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("platform", choices=["linux", "windows", "macos"])
    parser.add_argument("project_id", type=int)
    parser.add_argument("--api-token-file", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--protected", action="store_true",
                        help="Restrict to protected refs, for signing/release runners")
    args = parser.parse_args()
    if args.api_token_file.stat().st_mode & 0o077:
        parser.error("API token must be in an owner-only file")
    if args.output.exists():
        parser.error("Output already exists; revoke the old runner before replacing it")
    if args.project_id <= 0:
        parser.error("A positive project ID is required")
    # Windows/macOS shell jobs share an OS account. Require protected refs for
    # these persistent runners; use Linux containers for ordinary MR validation.
    protected = args.protected or args.platform != "linux"
    payload = {
        "runner_type": "project_type", "project_id": args.project_id,
        "description": f"homelab-{args.platform}", "locked": True,
        "run_untagged": False, "tag_list": [args.platform, "homelab"],
        "maximum_timeout": 7200,
        "access_level": "ref_protected" if protected else "not_protected",
    }
    request = urllib.request.Request(
        "https://gitlab.fahrican.com/api/v4/user/runners",
        data=json.dumps(payload).encode(), method="POST",
        headers={"PRIVATE-TOKEN": args.api_token_file.read_text().strip(),
                 "Content-Type": "application/json"},
    )
    # Reserve the output before creating server state; never overwrite a token.
    fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            created = json.load(response)
        if not re.fullmatch(r"glrt-[A-Za-z0-9_.-]+", created["token"]):
            raise ValueError("Unexpected runner authentication token format")
        with os.fdopen(fd, "w") as stream:
            fd = None
            json.dump({"id": created["id"], "token": created["token"],
                       "platform": args.platform, "project_id": args.project_id}, stream)
            stream.write("\n")
        print(f"Created runner {created['id']} for project {args.project_id}; token written privately.")
    finally:
        if fd is not None:
            os.close(fd)
    # A token is recoverable only at creation. Encrypt it with SOPS immediately;
    # an ambiguous API timeout requires reconciling server state before retrying.


if __name__ == "__main__":
    try:
        main()
    except urllib.error.HTTPError as error:
        raise SystemExit(f"Runner creation failed with HTTP {error.code}.") from None

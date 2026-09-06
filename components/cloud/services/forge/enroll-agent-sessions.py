#!/usr/bin/env python3
"""Enroll individual agent web sessions for private Forgejo Actions evidence.

Run from the infrastructure development shell as the workstation owner.
Passwords stay in SOPS and memory. API operations retain repository-scoped PATs;
these account-scoped sessions are used only by the fixed-repository evidence CLI.
"""

import argparse
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import subprocess
import tempfile

import requests
import yaml

URL = "https://git.fahrican.com"
REPOSITORY = "funforgiven/atollion"
IDENTITIES = ("atollion-coordinator", "atollion-worker-1", "atollion-worker-2", "atollion-worker-3")
RECOVERY = Path("deployments/homelab/cloud/host-runtime/atollion-agents.sops.yaml")


class Inputs(HTMLParser):
    def __init__(self):
        super().__init__()
        self.values = {}

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "input" and "name" in attributes:
            self.values[attributes["name"]] = attributes.get("value", "")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--identity", choices=IDENTITIES, action="append")
    parser.add_argument("--state-directory", type=Path,
                        default=Path.home() / ".local/state/atollion-forge")
    args = parser.parse_args()
    os.umask(0o077)
    encrypted = subprocess.run(["sops", "decrypt", str(RECOVERY)], capture_output=True, check=True).stdout
    identities = json.loads(yaml.safe_load(encrypted)["stringData"]["identities.json"])
    for name in args.identity or IDENTITIES:
        entry = identities[name]
        directory = args.state_directory / name
        credentials = json.loads((directory / "credentials.json").read_text())
        if (credentials["username"] != name or credentials["user_id"] != entry["user_id"]
                or credentials["repository"] != REPOSITORY or credentials["url"] != URL):
            raise RuntimeError("Local identity does not match encrypted enrollment")
        session = requests.Session()
        page = session.get(URL + "/user/login", timeout=30, allow_redirects=False)
        if page.status_code != 200:
            raise RuntimeError("Cannot read the private login form")
        form = Inputs()
        form.feed(page.text)
        # Forgejo 15 uses net/http CrossOriginProtection, not a hidden form
        # token. Supply its same-origin metadata; preserve a token if a future
        # compatible form adds one again.
        login = {"user_name": name, "password": entry["password"], "remember": "on"}
        if form.values.get("_csrf"):
            login["_csrf"] = form.values["_csrf"]
        response = session.post(URL + "/user/login", data=login,
            headers={"Origin": URL, "Referer": URL + "/user/login", "Sec-Fetch-Site": "same-origin"},
            timeout=30, allow_redirects=False)
        if response.status_code not in (302, 303) or response.headers.get("Location") not in ("/", URL + "/"):
            raise RuntimeError("Account login did not complete; inspect approval or MFA policy")
        # Forgejo's API requires token/Basic auth and ignores browser cookies.
        # Bind the authenticated settings form's username to the exact ID from
        # the same account's Basic-authenticated API response.
        settings = session.get(URL + "/user/settings", timeout=30, allow_redirects=False)
        profile = Inputs()
        profile.feed(settings.text)
        if settings.status_code != 200 or profile.values.get("name") != name:
            raise RuntimeError("Authenticated settings form has the wrong account")
        identity = session.get(URL + "/api/v1/user", auth=(name, entry["password"]),
                               timeout=30, allow_redirects=False)
        if identity.status_code != 200:
            raise RuntimeError("Cannot verify authenticated web-session identity")
        actual = identity.json()
        if actual["login"] != name or actual["id"] != entry["user_id"] or actual["is_admin"]:
            raise RuntimeError("Authenticated web session has the wrong identity or administrator rights")
        check = session.get(URL + "/" + REPOSITORY + "/actions/runs/1/artifacts", timeout=30,
                            allow_redirects=False)
        if check.status_code != 200:
            raise RuntimeError("Enrolled session cannot read private Actions evidence")
        cookies = []
        for cookie in session.cookies:
            if cookie.domain.lstrip(".") != "git.fahrican.com" or cookie.path != "/":
                raise RuntimeError("Unexpected session-cookie scope")
            if not cookie.secure:
                # Language and flash preferences are not authentication and
                # do not belong in the evidence client's credential jar.
                continue
            cookies.append({key: getattr(cookie, key) for key in
                            ("name", "value", "domain", "path", "secure", "expires")})
        if not cookies:
            raise RuntimeError("No secure authentication cookies were issued")
        document = {"username": name, "user_id": entry["user_id"], "url": URL,
                    "repository": REPOSITORY, "cookies": cookies}
        with tempfile.NamedTemporaryFile(mode="w", dir=directory, prefix=".web-session-", delete=False) as output:
            temporary = Path(output.name)
            json.dump(document, output, indent=2)
            output.write("\n")
        temporary.chmod(0o600)
        temporary.replace(directory / "web-session.json")
        print("Verified individual Actions evidence session:", name, flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(str(error) if isinstance(error, RuntimeError) else type(error).__name__)
        raise SystemExit(1) from None

#!/usr/bin/env python3
import configparser
import os
from pathlib import Path

os.umask(0o077)
root = Path("/var/lib/gitea")
for directory in ["custom/conf", "data", "git/repositories", "git/.ssh"]:
    (root / directory).mkdir(parents=True, exist_ok=True)
template = Path("/bootstrap/forgejo.ini").read_text()
# Forgejo permits top-level keys; configparser requires a section for them.
config = configparser.ConfigParser(interpolation=None)
config.optionxform = str
config.read_string("[DEFAULT]\n" + template)
for section, key, secret in [
    ("security", "SECRET_KEY", "forgejo-secret-key"),
    ("security", "INTERNAL_TOKEN", "forgejo-internal-token"),
    ("server", "LFS_JWT_SECRET", "forgejo-lfs-secret"),
    ("oauth2", "JWT_SECRET", "forgejo-oauth-secret"),
    ("metrics", "TOKEN", "forgejo-metrics-token"),
]:
    if not config.has_section(section):
        config.add_section(section)
    config.set(section, key, (Path("/run/forge-secrets") / secret).read_text().strip())
destination = root / "custom/conf/app.ini"
with destination.open("w") as output:
    config.write(output)
destination.write_text(destination.read_text().removeprefix("[DEFAULT]\n"))
destination.chmod(0o600)

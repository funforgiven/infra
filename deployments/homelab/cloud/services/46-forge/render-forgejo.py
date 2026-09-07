#!/usr/bin/env python3
import configparser
import os
from pathlib import Path
import stat
import tempfile

def install_signing_key(directory, secret_directory):
    # Keep the instance key stable across restarts/restores. Forgejo does not
    # currently support transparent instance-key rotation. Never reuse agent keys.
    if directory.resolve() != directory.absolute() or directory.exists() and not directory.is_dir():
        raise ValueError("Invalid instance signing directory")
    files = {
        directory / "instance-signing": (secret_directory / "private-key").read_bytes(),
        directory / "instance-signing.pub": (secret_directory / "public-key").read_bytes(),
    }
    for destination, data in files.items():
        if not data or destination.is_symlink():
            raise ValueError("Invalid instance signing key material or destination")
        if destination.exists() and not stat.S_ISREG(destination.stat().st_mode):
            raise ValueError("Instance signing key must be a regular file")
        if destination.exists() and destination.read_bytes() != data:
            raise ValueError("Instance signing key changed; explicit recovery review is required")
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    directory.chmod(0o700)
    for destination, data in files.items():
        if not destination.exists():
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(dir=directory, prefix=".instance-signing-", delete=False) as output:
                    temporary = Path(output.name)
                    output.write(data)
                    output.flush()
                    os.fsync(output.fileno())
                # Publish a complete file without replacing any existing key.
                os.link(temporary, destination)
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
        destination.chmod(0o600)
    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def main():
    os.umask(0o077)
    root = Path("/var/lib/gitea")
    for directory in ["custom/conf", "data", "git/repositories", "git/.ssh"]:
        (root / directory).mkdir(parents=True, exist_ok=True)
    install_signing_key(root / "git/.ssh", Path("/run/forge-signing"))
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
        ("mailer", "PASSWD", "FORGEJO_RESEND_API_KEY"),
    ]:
        if not config.has_section(section):
            config.add_section(section)
        config.set(section, key, (Path("/run/forge-secrets") / secret).read_text().strip())
    destination = root / "custom/conf/app.ini"
    with destination.open("w") as output:
        config.write(output)
    destination.write_text(destination.read_text().removeprefix("[DEFAULT]\n"))
    destination.chmod(0o600)


if __name__ == "__main__":
    main()

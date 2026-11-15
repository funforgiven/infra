"""Enroll instawow API credentials into the workstation's SOPS document."""

import argparse
import getpass
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile

PROVIDERS = {
    "curseforge": ("cfcore", "INSTAWOW_CURSEFORGE_API_KEY"),
    "github": ("github", "INSTAWOW_GITHUB_TOKEN"),
}
SECRET_FILE = Path("secrets/instawow.json")


def sops(*arguments, input=None, cwd=None):
    result = subprocess.run(
        ["sops", *arguments], input=input, cwd=cwd, text=True, capture_output=True, check=False
    )
    if result.returncode:
        # SOPS output can include source data. Keep errors independent of it.
        raise RuntimeError("SOPS could not process the instawow credential document")
    return result.stdout


def enroll(root, provider, value):
    if not value or any(character in value for character in "\r\n"):
        raise ValueError("The credential must be a non-empty single-line value")
    destination = root / SECRET_FILE
    if destination.is_symlink() or not destination.is_file():
        raise ValueError("The declared SOPS destination must be a regular file")
    original = destination.read_bytes()
    document = json.loads(sops("decrypt", "--output-type", "binary", str(destination)))
    if not isinstance(document, dict):
        raise ValueError("The instawow credential document must contain a JSON object")
    document[PROVIDERS[provider][0]] = value
    ciphertext = sops(
        "encrypt", "--input-type", "binary", "--output-type", "binary",
        "--filename-override", str(SECRET_FILE), "/dev/stdin",
        input=json.dumps(document), cwd=root,
    )
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", dir=destination.parent, prefix=".instawow-", suffix=".json", delete=False
        ) as output:
            temporary = Path(output.name)
            output.write(ciphertext)
            output.flush()
            os.fsync(output.fileno())
        verified = json.loads(sops("decrypt", "--output-type", "binary", str(temporary)))
        if verified != document:
            raise RuntimeError("The encrypted credential failed round-trip verification")
        if destination.read_bytes() != original:
            raise RuntimeError("The credential document changed during enrollment; retry")
        temporary.replace(destination)
        descriptor = os.open(destination.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def enroll_from_file(root, provider, intake_directory):
    path = intake_directory / f"{PROVIDERS[provider][1]}.key"
    descriptor = os.open(path, os.O_RDWR | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "r+") as intake:
        info = os.fstat(intake.fileno())
        if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600:
            raise ValueError("The intake file must be a regular file with mode 0600")
        value = intake.read().removesuffix("\n")
        enroll(root, provider, value)
        intake.seek(0)
        intake.truncate()
        intake.flush()
        os.fsync(intake.fileno())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("provider", choices=PROVIDERS, nargs="?", default="curseforge")
    parser.add_argument("--from-file", action="store_true")
    parser.add_argument("--intake-directory", type=Path)
    args = parser.parse_args()
    if args.intake_directory is not None and not args.from_file:
        parser.error("--intake-directory requires --from-file")
    try:
        root = Path(subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"], text=True
        ).strip())
        if args.from_file:
            enroll_from_file(root, args.provider, args.intake_directory or root / "secrets")
        else:
            value = getpass.getpass(f"Enter {args.provider} API credential: ")
            if value != getpass.getpass("Repeat credential: "):
                raise ValueError("Credentials did not match")
            enroll(root, args.provider, value)
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError):
        print("Credential enrollment failed; the intake was not cleared. "
              "Check the file permissions, SOPS identity, and non-empty single-line value.",
              file=sys.stderr)
        return 1
    print(f"Enrolled {args.provider} credential in {SECRET_FILE}; no credential value was printed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Read and write base64 values in SOPS Secret documents without printing them."""

from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys
from pathlib import Path

import yaml


class SopsCredentialError(RuntimeError):
    """An error that can be printed without exposing credentials."""


class SopsCredentialStore:
    def __init__(self, repository_root: Path):
        self.repository_root = repository_root.resolve()
        self._decrypted: dict[Path, dict] = {}

    def _path(self, relative_path: Path) -> Path:
        path = (self.repository_root / relative_path).resolve()
        if not path.is_relative_to(self.repository_root) or not path.is_file():
            raise SopsCredentialError(f"invalid SOPS destination {relative_path}")
        return path

    def read(self, secret_file: Path, credential: str) -> str | None:
        path = self._path(secret_file)
        try:
            document = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as error:
            raise SopsCredentialError(
                f"cannot inspect SOPS destination {secret_file}"
            ) from error
        value = document.get("data", {}).get(credential) if isinstance(document, dict) else None
        if value is None:
            return None
        if not isinstance(value, str) or not value.startswith("ENC["):
            raise SopsCredentialError(f"{credential} is not SOPS ciphertext")
        plaintext = self._data(path).get(credential)
        if not isinstance(plaintext, str):
            raise SopsCredentialError(f"cannot decrypt existing {credential}")
        try:
            return base64.b64decode(plaintext.strip(), validate=True).decode("utf-8")
        except (ValueError, UnicodeDecodeError) as error:
            raise SopsCredentialError(f"existing {credential} has invalid encoding") from error

    def _data(self, path: Path) -> dict:
        """Decrypt one SOPS file once; writes through this store invalidate it."""
        data = self._decrypted.get(path)
        if data is not None:
            return data
        result = subprocess.run(
            ["sops", "decrypt", "--output-type", "json", str(path)],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if result.returncode != 0:
            raise SopsCredentialError(f"cannot decrypt SOPS destination {path.name}")
        try:
            data = json.loads(result.stdout).get("data")
        except (json.JSONDecodeError, AttributeError) as error:
            raise SopsCredentialError(f"cannot parse SOPS destination {path.name}") from error
        if not isinstance(data, dict):
            raise SopsCredentialError(f"SOPS destination {path.name} has no data mapping")
        self._decrypted[path] = data
        return data

    def _set(self, path: Path, credential: str, value: str) -> None:
        self._decrypted.pop(path, None)
        encoded = base64.b64encode(value.encode("utf-8")).decode("ascii")
        result = subprocess.run(
            ["sops", "set", "--value-stdin", str(path), f'["data"]["{credential}"]'],
            input=json.dumps(encoded),
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if result.returncode != 0:
            raise SopsCredentialError(
                f"cannot encrypt {credential} into its SOPS destination"
            )

    def _unset(self, path: Path, credential: str) -> None:
        self._decrypted.pop(path, None)
        result = subprocess.run(
            ["sops", "unset", str(path), f'["data"]["{credential}"]'],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if result.returncode != 0:
            raise SopsCredentialError(f"cannot remove partial {credential} ciphertext")

    @staticmethod
    def _sync(path: Path) -> None:
        try:
            descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            directory_descriptor = os.open(
                path.parent,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
            )
            try:
                os.fsync(directory_descriptor)
            finally:
                os.close(directory_descriptor)
        except OSError as error:
            raise SopsCredentialError(
                f"cannot durably persist SOPS destination {path.name}"
            ) from error

    def _restore(
        self,
        path: Path,
        secret_file: Path,
        previous: dict[str, str | None],
        attempted: list[str],
    ) -> None:
        for credential in reversed(attempted):
            old_value = previous[credential]
            if old_value is None:
                try:
                    current_value = self.read(secret_file, credential)
                except SopsCredentialError:
                    self._unset(path, credential)
                else:
                    if current_value is not None:
                        self._unset(path, credential)
            else:
                self._set(path, credential, old_value)
        self._sync(path)
        for credential in attempted:
            if self.read(secret_file, credential) != previous[credential]:
                raise SopsCredentialError(
                    f"cannot verify rollback of {credential} in its SOPS destination"
                )

    def write(self, secret_file: Path, values: dict[str, str]) -> None:
        """Persist and decrypt-verify all values, restoring prior values on failure."""
        path = self._path(secret_file)
        previous = {credential: self.read(secret_file, credential) for credential in values}
        attempted: list[str] = []
        try:
            for credential, value in values.items():
                attempted.append(credential)
                self._set(path, credential, value)
            self._sync(path)
            for credential, value in values.items():
                if self.read(secret_file, credential) != value:
                    raise SopsCredentialError(
                        f"cannot verify encrypted {credential} in its SOPS destination"
                    )
        except SopsCredentialError:
            try:
                self._restore(path, secret_file, previous, attempted)
            except SopsCredentialError as rollback_error:
                raise SopsCredentialError(
                    f"cannot restore SOPS destination {secret_file} after a failed update"
                ) from rollback_error
            raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    commands = parser.add_subparsers(dest="command", required=True)
    read = commands.add_parser("read", help="print one decrypted value to stdout")
    write = commands.add_parser(
        "write", help="encrypt stdin as one value, verifying and rolling back on failure"
    )
    write.add_argument(
        "--no-replace", action="store_true", help="refuse to replace an existing value"
    )
    for command in (read, write):
        command.add_argument("secret_file", type=Path)
        command.add_argument("credential")
    arguments = parser.parse_args()
    store = SopsCredentialStore(arguments.repository_root)
    try:
        if arguments.command == "read":
            value = store.read(arguments.secret_file, arguments.credential)
            if value is None:
                raise SopsCredentialError(f"{arguments.credential} is not enrolled")
            sys.stdout.write(value)
            return 0
        if arguments.no_replace and (
            store.read(arguments.secret_file, arguments.credential) is not None
        ):
            raise SopsCredentialError(f"{arguments.credential} already exists")
        value = sys.stdin.read()
        if not value:
            raise SopsCredentialError(f"{arguments.credential} value is empty")
        store.write(arguments.secret_file, {arguments.credential: value})
        return 0
    except SopsCredentialError as error:
        print(f"sops-credential: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

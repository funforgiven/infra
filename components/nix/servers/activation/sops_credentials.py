"""Narrow, no-echo access to base64-encoded values in SOPS Secret documents."""

from __future__ import annotations

import base64
import json
import subprocess
from pathlib import Path

import yaml


class SopsCredentialError(RuntimeError):
    """A safe-to-display SOPS credential error."""


class SopsCredentialStore:
    def __init__(self, repository_root: Path):
        self.repository_root = repository_root.resolve()

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
        result = subprocess.run(
            ["sops", "decrypt", "--extract", f'["data"]["{credential}"]', str(path)],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if result.returncode != 0:
            raise SopsCredentialError(f"cannot decrypt existing {credential}")
        try:
            return base64.b64decode(result.stdout.strip(), validate=True).decode("utf-8")
        except (ValueError, UnicodeDecodeError) as error:
            raise SopsCredentialError(f"existing {credential} has invalid encoding") from error

    def _set(self, path: Path, credential: str, value: str) -> None:
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
        result = subprocess.run(
            ["sops", "unset", str(path), f'["data"]["{credential}"]'],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if result.returncode != 0:
            raise SopsCredentialError(f"cannot remove partial {credential} ciphertext")

    def write(self, secret_file: Path, values: dict[str, str]) -> None:
        path = self._path(secret_file)
        previous = {credential: self.read(secret_file, credential) for credential in values}
        completed: list[str] = []
        try:
            for credential, value in values.items():
                self._set(path, credential, value)
                completed.append(credential)
        except SopsCredentialError:
            for credential in reversed(completed):
                old_value = previous[credential]
                if old_value is None:
                    self._unset(path, credential)
                else:
                    self._set(path, credential, old_value)
            raise

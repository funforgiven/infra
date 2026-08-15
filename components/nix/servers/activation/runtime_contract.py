#!/usr/bin/env python3
"""Read and validate the services runtime credential contract."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import yaml


CONTRACT_PATH = Path(
    "deployments/homelab/cloud/undercloud/82-services-cluster/runtime-contract.yaml"
)
CLUSTER_SECTIONS = (
    "credentials",
    "postFoundationCredentials",
    "postDeploymentCredentials",
)
KEY_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]+$")


class ContractError(ValueError):
    """The runtime contract is invalid or incomplete."""


@dataclass(frozen=True)
class Credential:
    name: str
    secret_file: Path
    consumer: str


class RuntimeContract:
    def __init__(self, repository_root: Path, document: dict):
        self.repository_root = repository_root.resolve()
        self.document = document
        self.credentials = self._credentials()
        self.generated = self._generated_secrets()
        self._validate()

    @classmethod
    def load(cls, repository_root: Path) -> "RuntimeContract":
        path = repository_root / CONTRACT_PATH
        try:
            config_map = yaml.safe_load(path.read_text(encoding="utf-8"))
            document = yaml.safe_load(config_map["data"]["required-keys.yaml"])
        except (OSError, KeyError, TypeError, yaml.YAMLError) as error:
            raise ContractError(f"cannot read runtime contract {path}: {error}") from error
        if not isinstance(document, dict):
            raise ContractError("runtime contract payload must be a mapping")
        return cls(repository_root, document)

    def _credential_file(self, value: object, label: str) -> Path:
        if not isinstance(value, str) or not value:
            raise ContractError(f"{label} must be a non-empty repository-relative path")
        path = Path(value)
        if path.is_absolute() or ".." in path.parts:
            raise ContractError(f"{label} must stay inside the repository")
        resolved = (self.repository_root / path).resolve()
        if not resolved.is_relative_to(self.repository_root):
            raise ContractError(f"{label} resolves outside the repository")
        return path

    @staticmethod
    def _grouped_keys(groups: object, label: str) -> Iterable[str]:
        if not isinstance(groups, dict) or not groups:
            raise ContractError(f"{label} must be a non-empty mapping")
        for group, keys in groups.items():
            if not isinstance(group, str) or not isinstance(keys, list):
                raise ContractError(f"{label} contains an invalid group")
            for key in keys:
                if not isinstance(key, str):
                    raise ContractError(f"{label}.{group} contains a non-string key")
                yield key

    def _credentials(self) -> tuple[Credential, ...]:
        cluster_file = self._credential_file(
            self.document.get("secretFile"), "secretFile"
        )
        credentials: list[Credential] = []
        for section in CLUSTER_SECTIONS:
            for key in self._grouped_keys(self.document.get(section), section):
                credentials.append(Credential(key, cluster_file, "services-cluster"))

        host_credentials = self.document.get("hostCredentials")
        if not isinstance(host_credentials, dict) or not host_credentials:
            raise ContractError("hostCredentials must be a non-empty mapping")
        for consumer, definition in host_credentials.items():
            if not isinstance(consumer, str) or not isinstance(definition, dict):
                raise ContractError("hostCredentials contains an invalid consumer")
            secret_file = self._credential_file(
                definition.get("secretFile"),
                f"hostCredentials.{consumer}.secretFile",
            )
            keys = definition.get("keys")
            if not isinstance(keys, list) or not keys:
                raise ContractError(f"hostCredentials.{consumer}.keys must be a list")
            for key in keys:
                if not isinstance(key, str):
                    raise ContractError(
                        f"hostCredentials.{consumer}.keys contains a non-string key"
                    )
                credentials.append(Credential(key, secret_file, consumer))
        return tuple(credentials)

    def _generated_secrets(self) -> tuple[str, ...]:
        values = self.document.get("generatedApplicationSecrets")
        if not isinstance(values, list) or not values:
            raise ContractError("generatedApplicationSecrets must be a non-empty list")
        if any(not isinstance(value, str) for value in values):
            raise ContractError("generatedApplicationSecrets contains a non-string key")
        return tuple(values)

    def _validate(self) -> None:
        if self.document.get("schemaVersion") != 2:
            raise ContractError("runtime contract schemaVersion must be 2")
        names = [credential.name for credential in self.credentials]
        names.extend(self.generated)
        invalid = sorted(name for name in names if not KEY_PATTERN.fullmatch(name))
        if invalid:
            raise ContractError(f"invalid credential names: {invalid}")
        duplicates = sorted({name for name in names if names.count(name) > 1})
        if duplicates:
            raise ContractError(f"duplicate credential names: {duplicates}")

    def credential(self, name: str) -> Credential:
        matches = [item for item in self.credentials if item.name == name]
        if len(matches) != 1:
            raise ContractError(f"unknown services credential key: {name}")
        return matches[0]

    def secret_files(self) -> tuple[Path, ...]:
        return tuple(sorted({item.secret_file for item in self.credentials}))

    def verify_ciphertext(self) -> None:
        expected: dict[Path, set[str]] = {
            path: set() for path in self.secret_files()
        }
        for credential in self.credentials:
            expected[credential.secret_file].add(credential.name)
        cluster_file = self._credential_file(
            self.document.get("secretFile"), "secretFile"
        )
        expected[cluster_file].update(self.generated)

        for relative_path, keys in expected.items():
            path = self.repository_root / relative_path
            try:
                document = yaml.safe_load(path.read_text(encoding="utf-8"))
            except (OSError, yaml.YAMLError) as error:
                raise ContractError(f"cannot read SOPS document {path}: {error}") from error
            if not isinstance(document, dict) or not isinstance(document.get("sops"), dict):
                raise ContractError(f"{relative_path} has no SOPS metadata")
            data = document.get("data")
            if not isinstance(data, dict):
                raise ContractError(f"{relative_path} has no data mapping")
            missing = sorted(
                key
                for key in keys
                if not str(data.get(key, "")).startswith("ENC[")
            )
            if missing:
                raise ContractError(
                    f"{relative_path} is missing encrypted keys: {missing}"
                )


def repository_root(argument: str | None) -> Path:
    if argument:
        return Path(argument)
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        check=True,
        capture_output=True,
        text=True,
    )
    return Path(result.stdout.strip())


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--repository-root")
    subparsers = result.add_subparsers(dest="command", required=True)
    subparsers.add_parser("schema", help="validate the contract schema")
    subparsers.add_parser("keys", help="list enrollable credential keys")
    key_file = subparsers.add_parser(
        "key-file", help="print the SOPS document for one credential"
    )
    key_file.add_argument("key")
    subparsers.add_parser("secret-files", help="list contract-managed SOPS documents")
    subparsers.add_parser(
        "verify-ciphertext", help="require every declared key as SOPS ciphertext"
    )
    return result


def main() -> int:
    arguments = parser().parse_args()
    try:
        contract = RuntimeContract.load(repository_root(arguments.repository_root))
        if arguments.command == "schema":
            print(f"runtime credential contract is valid ({len(contract.credentials)} keys)")
        elif arguments.command == "keys":
            for credential in sorted(contract.credentials, key=lambda item: item.name):
                print(credential.name)
        elif arguments.command == "key-file":
            print(contract.credential(arguments.key).secret_file)
        elif arguments.command == "secret-files":
            for path in contract.secret_files():
                print(path)
        elif arguments.command == "verify-ciphertext":
            contract.verify_ciphertext()
            print("all runtime credentials are present as SOPS ciphertext")
        else:  # pragma: no cover - argparse enforces the command set.
            raise AssertionError(arguments.command)
    except (ContractError, subprocess.CalledProcessError) as error:
        print(f"runtime-contract: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

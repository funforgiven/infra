#!/usr/bin/env python3
"""Reconcile the services Backblaze bucket policy and scoped application keys."""

from __future__ import annotations

import argparse
import base64
import json
import os
import stat
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import yaml

from runtime_contract import ContractError, RuntimeContract
from sops_credentials import SopsCredentialError, SopsCredentialStore


BACKUP_CONTRACT_PATH = Path("deployments/homelab/cloud/backup-destination.yaml")
AUTHORIZE_URL = "https://api.backblazeb2.com/b2api/v4/b2_authorize_account"
REQUIRED_CAPABILITIES = frozenset(
    {
        "deleteFiles",
        "listAllBucketNames",
        "listFiles",
        "readBuckets",
        "readFiles",
        "writeFiles",
    }
)


class ReconcileError(RuntimeError):
    """A safe-to-display reconciliation error."""


@dataclass(frozen=True)
class KeySpec:
    name: str
    prefix: str
    capabilities: tuple[str, ...]
    secret_file: Path
    id_credential: str
    key_credential: str


@dataclass(frozen=True)
class BackupContract:
    bucket_name: str
    lifecycle_rules: tuple[dict, ...]
    master_id_file: str
    master_key_file: str
    clear_after_success: bool
    keys: tuple[KeySpec, ...]

    @classmethod
    def load(cls, repository_root: Path) -> "BackupContract":
        path = repository_root / BACKUP_CONTRACT_PATH
        try:
            document = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as error:
            raise ReconcileError(f"cannot read backup contract {path}") from error
        if not isinstance(document, dict) or document.get("provider") != "backblaze-b2":
            raise ReconcileError("backup contract must select provider backblaze-b2")
        bucket = _mapping(document.get("bucket"), "bucket")
        bootstrap = _mapping(bucket.get("operatorBootstrap"), "operator bootstrap")
        services = _mapping(document.get("services"), "services")
        kubernetes = _mapping(services.get("kubernetes"), "services.kubernetes")
        host_capabilities = _string_list(
            services.get("hostCapabilities"), "services.hostCapabilities"
        )
        specs = [_key_spec(kubernetes, kubernetes.get("capabilities"), "kubernetes")]
        hosts = services.get("hosts")
        if not isinstance(hosts, list) or not hosts:
            raise ReconcileError("services.hosts must be a non-empty list")
        for index, host in enumerate(hosts):
            specs.append(
                _key_spec(
                    _mapping(host, f"services.hosts[{index}]"),
                    host_capabilities,
                    f"host {index}",
                )
            )
        lifecycle_rules = bucket.get("lifecycleRules")
        if not isinstance(lifecycle_rules, list) or not lifecycle_rules:
            raise ReconcileError("bucket.lifecycleRules must be a non-empty list")
        contract = cls(
            bucket_name=_string(bucket.get("name"), "bucket.name"),
            lifecycle_rules=tuple(_mapping(rule, "lifecycle rule") for rule in lifecycle_rules),
            master_id_file=_safe_basename(
                bootstrap.get("applicationKeyIdFile"), "applicationKeyIdFile"
            ),
            master_key_file=_safe_basename(
                bootstrap.get("applicationKeyFile"), "applicationKeyFile"
            ),
            clear_after_success=bootstrap.get("clearAfterSuccess") is True,
            keys=tuple(specs),
        )
        contract.validate(repository_root)
        return contract

    def validate(self, repository_root: Path) -> None:
        if not self.clear_after_success:
            raise ReconcileError("operator bootstrap credentials must be cleared on success")
        if len(self.keys) != 4:
            raise ReconcileError("exactly four services backup keys must be declared")
        names = [spec.name for spec in self.keys]
        prefixes = [spec.prefix for spec in self.keys]
        credentials = [
            credential
            for spec in self.keys
            for credential in (spec.id_credential, spec.key_credential)
        ]
        for label, values in (
            ("application key names", names),
            ("application key prefixes", prefixes),
            ("credential targets", credentials),
        ):
            if len(values) != len(set(values)):
                raise ReconcileError(f"duplicate {label} in backup contract")
        runtime = RuntimeContract.load(repository_root)
        for spec in self.keys:
            if not spec.prefix.startswith("services/") or not spec.prefix.endswith("/"):
                raise ReconcileError(f"invalid services prefix for {spec.name}")
            if frozenset(spec.capabilities) != REQUIRED_CAPABILITIES:
                raise ReconcileError(f"invalid least-privilege capabilities for {spec.name}")
            for credential in (spec.id_credential, spec.key_credential):
                routed = runtime.provisioned_credential(credential)
                if routed.provisioner != "reconcile-services-backblaze":
                    raise ReconcileError(f"wrong provisioner for {credential}")
                if routed.secret_file != spec.secret_file:
                    raise ReconcileError(f"wrong SOPS destination for {credential}")


class CredentialStore(Protocol):
    def read(self, secret_file: Path, credential: str) -> str | None: ...

    def write(self, secret_file: Path, values: dict[str, str]) -> None: ...


class BackblazeClient:
    def __init__(self, master_id: str, master_key: str):
        basic = base64.b64encode(f"{master_id}:{master_key}".encode("utf-8")).decode("ascii")
        document = self._request(AUTHORIZE_URL, method="GET", authorization=f"Basic {basic}")
        try:
            storage = document["apiInfo"]["storageApi"]
            self.api_url = storage["apiUrl"]
            self.account_id = document["accountId"]
            self.authorization = document["authorizationToken"]
        except (KeyError, TypeError) as error:
            raise ReconcileError("Backblaze authorization returned an invalid response") from error

    @staticmethod
    def _request(
        url: str,
        *,
        method: str,
        authorization: str,
        payload: dict | None = None,
    ) -> dict:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=data,
            method=method,
            headers={"Authorization": authorization, "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                document = json.load(response)
        except urllib.error.HTTPError as error:
            raise ReconcileError(f"Backblaze API rejected a request with HTTP {error.code}") from error
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
            raise ReconcileError("Backblaze API request failed") from error
        if not isinstance(document, dict):
            raise ReconcileError("Backblaze API returned an invalid response")
        return document

    def call(self, operation: str, payload: dict) -> dict:
        try:
            return self._request(
                f"{self.api_url}/b2api/v4/{operation}",
                method="POST",
                authorization=self.authorization,
                payload=payload,
            )
        except ReconcileError as error:
            raise ReconcileError(f"{operation} failed: {error}") from error

    def bucket(self, name: str) -> dict:
        document = self.call(
            "b2_list_buckets", {"accountId": self.account_id, "bucketName": name}
        )
        buckets = document.get("buckets")
        if not isinstance(buckets, list) or len(buckets) != 1:
            raise ReconcileError(f"Backblaze bucket {name} was not found uniquely")
        return buckets[0]

    def keys(self) -> list[dict]:
        keys: list[dict] = []
        next_id: str | None = None
        while True:
            payload: dict[str, object] = {"accountId": self.account_id, "maxKeyCount": 1000}
            if next_id:
                payload["startApplicationKeyId"] = next_id
            document = self.call("b2_list_keys", payload)
            page = document.get("keys")
            if not isinstance(page, list):
                raise ReconcileError("Backblaze key inventory response is invalid")
            keys.extend(item for item in page if isinstance(item, dict))
            next_id = document.get("nextApplicationKeyId")
            if not next_id:
                return keys

    def update_bucket_policy(self, bucket: dict, lifecycle_rules: tuple[dict, ...]) -> bool:
        encryption = _encryption_value(bucket)
        encryption_matches = (
            isinstance(encryption, dict)
            and encryption.get("mode") == "SSE-B2"
            and encryption.get("algorithm") in (None, "AES256")
        )
        desired_rules = list(lifecycle_rules)
        if (
            bucket.get("bucketType") == "allPrivate"
            and encryption_matches
            and bucket.get("lifecycleRules") == desired_rules
        ):
            return False
        payload = {
            "accountId": self.account_id,
            "bucketId": bucket["bucketId"],
            "bucketType": "allPrivate",
            "defaultServerSideEncryption": {"mode": "SSE-B2", "algorithm": "AES256"},
            "lifecycleRules": desired_rules,
        }
        if isinstance(bucket.get("revision"), int):
            payload["ifRevisionIs"] = bucket["revision"]
        self.call("b2_update_bucket", payload)
        return True

    def create_key(self, bucket_id: str, spec: KeySpec) -> tuple[str, str]:
        document = self.call(
            "b2_create_key",
            {
                "accountId": self.account_id,
                "keyName": spec.name,
                "bucketIds": [bucket_id],
                "capabilities": list(spec.capabilities),
                "namePrefix": spec.prefix,
            },
        )
        try:
            return document["applicationKeyId"], document["applicationKey"]
        except (KeyError, TypeError) as error:
            raise ReconcileError(f"Backblaze did not return new material for {spec.name}") from error

    def delete_key(self, key_id: str) -> None:
        self.call("b2_delete_key", {"applicationKeyId": key_id})


class ServicesBackblazeReconciler:
    def __init__(
        self,
        contract: BackupContract,
        client: BackblazeClient,
        store: CredentialStore,
    ):
        self.contract = contract
        self.client = client
        self.store = store

    def reconcile(self, *, apply: bool, rotate: bool) -> list[str]:
        bucket = self.client.bucket(self.contract.bucket_name)
        reports: list[str] = []
        policy_drift = not _bucket_policy_matches(bucket, self.contract.lifecycle_rules)
        if apply:
            changed = self.client.update_bucket_policy(bucket, self.contract.lifecycle_rules)
            reports.append(f"bucket policy: {'updated' if changed else 'current'}")
        else:
            reports.append(f"bucket policy: {'drift' if policy_drift else 'current'}")
        inventory = self.client.keys()
        bucket_id = _string(bucket.get("bucketId"), "Backblaze bucket ID")
        for spec in self.contract.keys:
            named = [item for item in inventory if item.get("keyName") == spec.name]
            stored_id = self.store.read(spec.secret_file, spec.id_credential)
            stored_key = self.store.read(spec.secret_file, spec.key_credential)
            exact = [item for item in named if _key_matches(item, bucket_id, spec)]
            current = (
                len(exact) == 1
                and len(named) == 1
                and stored_id == exact[0].get("applicationKeyId")
                and stored_key is not None
            )
            if current:
                reports.append(f"{spec.name}: current")
                continue
            if not apply:
                reports.append(f"{spec.name}: reconciliation required")
                continue
            if named or stored_id is not None or stored_key is not None:
                if not rotate:
                    raise ReconcileError(
                        f"{spec.name} has existing or partial state; inspect it and rerun with --rotate"
                    )
                ids = {
                    item.get("applicationKeyId")
                    for item in named
                    if isinstance(item.get("applicationKeyId"), str)
                }
                if stored_id and any(item.get("applicationKeyId") == stored_id for item in inventory):
                    ids.add(stored_id)
                for key_id in ids:
                    self.client.delete_key(key_id)
            key_id, application_key = self.client.create_key(bucket_id, spec)
            try:
                self.store.write(
                    spec.secret_file,
                    {
                        spec.id_credential: key_id,
                        spec.key_credential: application_key,
                    },
                )
            except SopsCredentialError:
                try:
                    self.client.delete_key(key_id)
                finally:
                    raise
            reports.append(f"{spec.name}: created and encrypted")
        return reports


class MasterCredentialFiles:
    def __init__(self, directory: Path, id_name: str, key_name: str):
        self.directory = directory.resolve()
        self.id_path = self.directory / id_name
        self.key_path = self.directory / key_name

    @staticmethod
    def _read(path: Path) -> str:
        try:
            file_stat = path.lstat()
        except OSError as error:
            raise ReconcileError(f"missing bootstrap file {path.name}") from error
        if not stat.S_ISREG(file_stat.st_mode) or stat.S_IMODE(file_stat.st_mode) != 0o600:
            raise ReconcileError(f"{path.name} must be a regular mode-0600 file")
        try:
            value = path.read_text(encoding="utf-8").strip()
        except OSError as error:
            raise ReconcileError(f"cannot read bootstrap file {path.name}") from error
        if not value or any(character.isspace() for character in value):
            raise ReconcileError(f"{path.name} must contain one non-empty credential")
        return value

    def read(self) -> tuple[str, str]:
        return self._read(self.id_path), self._read(self.key_path)

    def clear(self) -> None:
        for path in (self.id_path, self.key_path):
            descriptor = os.open(path, os.O_WRONLY | os.O_TRUNC | os.O_NOFOLLOW)
            os.close(descriptor)


def _mapping(value: object, label: str) -> dict:
    if not isinstance(value, dict):
        raise ReconcileError(f"{label} must be a mapping")
    return value


def _string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ReconcileError(f"{label} must be a non-empty string")
    return value


def _string_list(value: object, label: str) -> tuple[str, ...]:
    if (
        not isinstance(value, (list, tuple))
        or not value
        or not all(isinstance(item, str) for item in value)
    ):
        raise ReconcileError(f"{label} must be a non-empty string list")
    return tuple(sorted(value))


def _safe_basename(value: object, label: str) -> str:
    path = Path(_string(value, label))
    if path.parent != Path("secrets") or not path.name.endswith(".key"):
        raise ReconcileError(f"{label} must name one file below secrets/")
    return path.name


def _key_spec(definition: dict, capabilities: object, label: str) -> KeySpec:
    secret_file = Path(_string(definition.get("secretFile"), f"{label}.secretFile"))
    if secret_file.is_absolute() or ".." in secret_file.parts:
        raise ReconcileError(f"{label}.secretFile must stay inside the repository")
    return KeySpec(
        name=_string(definition.get("keyName"), f"{label}.keyName"),
        prefix=_string(definition.get("namePrefix"), f"{label}.namePrefix"),
        capabilities=_string_list(capabilities, f"{label}.capabilities"),
        secret_file=secret_file,
        id_credential=_string(
            definition.get("idField"),
            f"{label}.idField",
        ),
        key_credential=_string(
            definition.get("valueField"),
            f"{label}.valueField",
        ),
    )


def _key_matches(item: dict, bucket_id: str, spec: KeySpec) -> bool:
    return (
        item.get("keyName") == spec.name
        and item.get("bucketIds") == [bucket_id]
        and item.get("namePrefix") == spec.prefix
        and set(item.get("capabilities", [])) == set(spec.capabilities)
    )


def _bucket_policy_matches(bucket: dict, lifecycle_rules: tuple[dict, ...]) -> bool:
    encryption = _encryption_value(bucket)
    return (
        bucket.get("bucketType") == "allPrivate"
        and isinstance(encryption, dict)
        and encryption.get("mode") == "SSE-B2"
        and bucket.get("lifecycleRules") == list(lifecycle_rules)
    )


def _encryption_value(bucket: dict) -> dict:
    encryption = bucket.get("defaultServerSideEncryption", {})
    if not isinstance(encryption, dict):
        return {}
    value = encryption.get("value")
    return value if isinstance(value, dict) else encryption


def argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("check", "apply"))
    parser.add_argument("--repository-root", type=Path)
    parser.add_argument("--bootstrap-directory", type=Path)
    parser.add_argument(
        "--rotate",
        action="store_true",
        help="replace conflicting or partial declared application keys",
    )
    return parser


def main() -> int:
    arguments = argument_parser().parse_args()
    repository_root = (
        arguments.repository_root.resolve()
        if arguments.repository_root
        else Path(
            subprocess.run(
                ["git", "rev-parse", "--show-toplevel"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
        )
    )
    try:
        contract = BackupContract.load(repository_root)
        bootstrap_directory = (
            arguments.bootstrap_directory.resolve()
            if arguments.bootstrap_directory
            else repository_root / "secrets"
        )
        files = MasterCredentialFiles(
            bootstrap_directory, contract.master_id_file, contract.master_key_file
        )
        master_id, master_key = files.read()
        client = BackblazeClient(master_id, master_key)
        del master_id, master_key
        reconciler = ServicesBackblazeReconciler(
            contract, client, SopsCredentialStore(repository_root)
        )
        reports = reconciler.reconcile(
            apply=arguments.command == "apply", rotate=arguments.rotate
        )
        if arguments.command == "apply" and contract.clear_after_success:
            files.clear()
        for report in reports:
            print(report)
        if arguments.command == "apply":
            print("Backblaze master bootstrap files were cleared after successful reconciliation.")
        else:
            print("Check completed without changing Backblaze or SOPS state.")
        return 0
    except (
        ContractError,
        ReconcileError,
        SopsCredentialError,
        subprocess.CalledProcessError,
    ) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

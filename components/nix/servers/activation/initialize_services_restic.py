#!/usr/bin/env python3
"""Initialize declared host Restic repositories with one ephemeral B2 key."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Protocol

from reconcile_services_backblaze import (
    BackblazeClient,
    BackupContract,
    KeySpec,
    MasterCredentialFiles,
    ReconcileError,
)
from runtime_contract import ContractError
from sops_credentials import SopsCredentialError, SopsCredentialStore


class BootstrapKeyClient(Protocol):
    def bucket(self, name: str) -> dict: ...

    def keys(self) -> list[dict]: ...

    def create_unscoped_key(
        self,
        bucket_id: str,
        name: str,
        capabilities: tuple[str, ...],
    ) -> tuple[str, str]: ...

    def delete_key(self, key_id: str) -> None: ...


class RepositoryRunner(Protocol):
    def ready(
        self,
        spec: KeySpec,
        key_id: str,
        application_key: str,
        password: str,
    ) -> bool: ...

    def initialize(
        self,
        spec: KeySpec,
        key_id: str,
        application_key: str,
        password: str,
    ) -> None: ...


class ResticRunner:
    def __init__(self, bucket_name: str, endpoint: str, region: str):
        executable = shutil.which("restic")
        if executable is None:
            raise ReconcileError("restic is unavailable")
        self.executable = executable
        self.bucket_name = bucket_name
        self.endpoint = endpoint.rstrip("/")
        self.region = region

    def _run(
        self,
        spec: KeySpec,
        key_id: str,
        application_key: str,
        password: str,
        arguments: list[str],
    ) -> subprocess.CompletedProcess[str]:
        environment = {
            "AWS_ACCESS_KEY_ID": key_id,
            "AWS_SECRET_ACCESS_KEY": application_key,
            "AWS_DEFAULT_REGION": self.region,
            "RESTIC_PASSWORD": password,
        }
        for name in ("PATH", "SSL_CERT_FILE", "NIX_SSL_CERT_FILE"):
            if name in os.environ:
                environment[name] = os.environ[name]
        repository = (
            f"s3:{self.endpoint}/{self.bucket_name}/{spec.prefix.rstrip('/')}"
        )
        return subprocess.run(
            [self.executable, "--repo", repository, *arguments],
            check=False,
            capture_output=True,
            text=True,
            env=environment,
        )

    def ready(
        self,
        spec: KeySpec,
        key_id: str,
        application_key: str,
        password: str,
    ) -> bool:
        return self._run(
            spec, key_id, application_key, password, ["cat", "config"]
        ).returncode == 0

    def initialize(
        self,
        spec: KeySpec,
        key_id: str,
        application_key: str,
        password: str,
    ) -> None:
        result = self._run(spec, key_id, application_key, password, ["init"])
        if result.returncode != 0:
            raise ReconcileError(f"cannot initialize Restic repository {spec.prefix}")


class ServicesResticInitializer:
    def __init__(
        self,
        contract: BackupContract,
        store: SopsCredentialStore,
        runner: RepositoryRunner,
    ):
        self.contract = contract
        self.store = store
        self.runner = runner

    @property
    def repositories(self) -> tuple[KeySpec, ...]:
        return tuple(
            spec
            for spec in self.contract.keys
            if spec.restic_password_credential is not None
        )

    def _material(self, spec: KeySpec) -> tuple[str, str, str]:
        if (
            spec.restic_password_credential is None
            or spec.restic_password_file is None
        ):
            raise ReconcileError(f"missing Restic password route for {spec.name}")
        key_id = self.store.read(spec.secret_file, spec.id_credential)
        application_key = self.store.read(spec.secret_file, spec.key_credential)
        password = self.store.read(
            spec.restic_password_file, spec.restic_password_credential
        )
        if not key_id or not application_key or not password:
            raise ReconcileError(f"missing encrypted Restic material for {spec.name}")
        return key_id, application_key, password

    def check(self) -> list[str]:
        reports: list[str] = []
        for spec in self.repositories:
            key_id, application_key, password = self._material(spec)
            ready = self.runner.ready(spec, key_id, application_key, password)
            reports.append(
                f"{spec.prefix}: {'ready' if ready else 'initialization required'}"
            )
        return reports

    def apply(self, client: BootstrapKeyClient) -> list[str]:
        bucket = client.bucket(self.contract.bucket_name)
        bucket_id = bucket.get("bucketId")
        if not isinstance(bucket_id, str) or not bucket_id:
            raise ReconcileError("Backblaze bucket has no valid ID")
        stale_ids = {
            item.get("applicationKeyId")
            for item in client.keys()
            if item.get("keyName") == self.contract.restic_bootstrap_name
            and isinstance(item.get("applicationKeyId"), str)
        }
        for key_id in stale_ids:
            client.delete_key(key_id)
        key_id, application_key = client.create_unscoped_key(
            bucket_id,
            self.contract.restic_bootstrap_name,
            self.contract.restic_bootstrap_capabilities,
        )
        reports: list[str] = []
        try:
            for spec in self.repositories:
                _, _, password = self._material(spec)
                if self.runner.ready(spec, key_id, application_key, password):
                    reports.append(f"{spec.prefix}: ready")
                    continue
                self.runner.initialize(spec, key_id, application_key, password)
                if not self.runner.ready(spec, key_id, application_key, password):
                    raise ReconcileError(
                        f"Restic repository verification failed for {spec.prefix}"
                    )
                reports.append(f"{spec.prefix}: initialized")
        finally:
            client.delete_key(key_id)
        reports.append("ephemeral Restic bootstrap key: revoked")
        return reports


def argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("check", "apply"))
    parser.add_argument("--repository-root", type=Path)
    parser.add_argument("--bootstrap-directory", type=Path)
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
        initializer = ServicesResticInitializer(
            contract,
            SopsCredentialStore(repository_root),
            ResticRunner(
                contract.bucket_name,
                contract.s3_endpoint,
                contract.region,
            ),
        )
        if arguments.command == "check":
            reports = initializer.check()
            suffix = "Check completed without changing Backblaze or repository state."
        else:
            bootstrap_directory = (
                arguments.bootstrap_directory.resolve()
                if arguments.bootstrap_directory
                else repository_root / "secrets"
            )
            files = MasterCredentialFiles(
                bootstrap_directory,
                contract.master_id_file,
                contract.master_key_file,
            )
            master_id, master_key = files.read()
            client = BackblazeClient(master_id, master_key)
            del master_id, master_key
            reports = initializer.apply(client)
            if contract.clear_after_success:
                files.clear()
            suffix = (
                "Backblaze master bootstrap files were cleared after successful "
                "repository initialization."
            )
        for report in reports:
            print(report)
        print(suffix)
        return 0
    except (
        ContractError,
        OSError,
        ReconcileError,
        SopsCredentialError,
        subprocess.CalledProcessError,
    ) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

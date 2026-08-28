#!/usr/bin/env python3
"""Initialize Restic repositories for service hosts."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Protocol

from reconcile_services_backblaze import (
    BackblazeClient,
    BackupContract,
    KeySpec,
    ReconcileError,
)
from runtime_contract import ContractError
from sops_credentials import SopsCredentialError, SopsCredentialStore


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
            [self.executable, "--no-cache", "--repo", repository, *arguments],
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
        environment = {"RESTIC_PASSWORD": password}
        if "PATH" in os.environ:
            environment["PATH"] = os.environ["PATH"]
        with tempfile.TemporaryDirectory(prefix="services-restic-") as directory:
            root = Path(directory)
            result = subprocess.run(
                [self.executable, "--repo", str(root), "init"],
                check=False,
                capture_output=True,
                text=True,
                env=environment,
            )
            if result.returncode != 0:
                raise ReconcileError(
                    f"cannot create local Restic repository for {spec.prefix}"
                )
            client = BackblazeClient(key_id, application_key)
            bucket = client.bucket(self.bucket_name)
            bucket_id = bucket.get("bucketId")
            if not isinstance(bucket_id, str) or not bucket_id:
                raise ReconcileError("Backblaze bucket has no valid ID")
            files = sorted(
                (path for path in root.rglob("*") if path.is_file()),
                key=lambda path: (path.name == "config", path.as_posix()),
            )
            uploaded: list[tuple[str, str]] = []
            try:
                for path in files:
                    relative = path.relative_to(root).as_posix()
                    uploaded.append(
                        client.upload_file(
                            bucket_id,
                            f"{spec.prefix}{relative}",
                            path.read_bytes(),
                        )
                    )
                if not self.ready(spec, key_id, application_key, password):
                    raise ReconcileError(
                        f"Restic repository verification failed for {spec.prefix}"
                    )
            except (OSError, ReconcileError):
                for file_name, file_id in reversed(uploaded):
                    client.delete_file_version(file_name, file_id)
                raise


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

    def apply(self) -> list[str]:
        reports: list[str] = []
        for spec in self.repositories:
            key_id, application_key, password = self._material(spec)
            if self.runner.ready(spec, key_id, application_key, password):
                reports.append(f"{spec.prefix}: ready")
                continue
            self.runner.initialize(spec, key_id, application_key, password)
            if not self.runner.ready(spec, key_id, application_key, password):
                raise ReconcileError(
                    f"Restic repository verification failed for {spec.prefix}"
                )
            reports.append(f"{spec.prefix}: initialized")
        return reports


def argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("check", "apply"))
    parser.add_argument("--repository-root", type=Path)
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
            reports = initializer.apply()
            suffix = "Restic repository initialization complete."
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

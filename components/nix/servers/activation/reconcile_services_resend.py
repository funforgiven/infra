#!/usr/bin/env python3
"""Create and rotate domain-scoped Resend sending keys directly into SOPS."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import yaml

from runtime_contract import ContractError, RuntimeContract
from sops_credentials import SopsCredentialError, SopsCredentialStore


RESEND_CONTRACT_PATH = Path("deployments/homelab/cloud/resend-sending-keys.yaml")
API_BASE = "https://api.resend.com"


class ResendReconcileError(RuntimeError):
    """A safe-to-display Resend reconciliation error."""


@dataclass(frozen=True)
class ResendKeySpec:
    name: str
    permission: str
    domain: str
    administration_file: Path
    administration_credential: str
    output_file: Path
    output_credential: str

    @classmethod
    def load(cls, repository_root: Path) -> "ResendKeySpec":
        path = repository_root / RESEND_CONTRACT_PATH
        try:
            document = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as error:
            raise ResendReconcileError(f"cannot read Resend contract {path}") from error
        if not isinstance(document, dict) or document.get("schemaVersion") != 1:
            raise ResendReconcileError("Resend contract must use schema version 1")
        keys = document.get("keys")
        if not isinstance(keys, dict) or set(keys) != {"stalwart"}:
            raise ResendReconcileError("Resend contract must declare only the Stalwart key")
        definition = keys["stalwart"]
        if not isinstance(definition, dict):
            raise ResendReconcileError("Resend Stalwart key must be a mapping")
        runtime = RuntimeContract.load(repository_root)
        administration_credential = _string(
            definition.get("administrationCredential"), "administrationCredential"
        )
        output_credential = _string(
            definition.get("outputCredential"), "outputCredential"
        )
        administration = runtime.credential(administration_credential)
        output = runtime.provisioned_credential(output_credential)
        if output.provisioner != "reconcile-services-resend":
            raise ResendReconcileError("Stalwart sending key has the wrong provisioner")
        spec = cls(
            name=_string(definition.get("name"), "name"),
            permission=_string(definition.get("permission"), "permission"),
            domain=_string(definition.get("domain"), "domain"),
            administration_file=administration.secret_file,
            administration_credential=administration_credential,
            output_file=output.secret_file,
            output_credential=output_credential,
        )
        if spec.permission != "sending_access" or spec.domain != "fahrican.com":
            raise ResendReconcileError("Stalwart must use sending access scoped to fahrican.com")
        if len(spec.name) > 50:
            raise ResendReconcileError("Resend key name exceeds the provider limit")
        return spec


class ResendClient:
    def __init__(self, administration_key: str):
        self.authorization = f"Bearer {administration_key}"

    def request(self, method: str, path: str, payload: dict | None = None) -> dict:
        request = urllib.request.Request(
            API_BASE + path,
            data=None if payload is None else json.dumps(payload).encode("utf-8"),
            method=method,
            headers={
                "Authorization": self.authorization,
                "Content-Type": "application/json",
                "User-Agent": "fahrican-infra-resend-key-reconciler/1.0",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                body = response.read()
                document = {} if not body else json.loads(body)
        except urllib.error.HTTPError as error:
            raise ResendReconcileError(
                f"Resend {method} {path} returned HTTP {error.code}"
            ) from error
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
            raise ResendReconcileError(f"Resend request {method} {path} failed") from error
        if not isinstance(document, dict):
            raise ResendReconcileError("Resend returned an invalid response")
        return document

    def domain(self, name: str) -> dict:
        document = self.request("GET", "/domains?limit=100")
        matches = [item for item in document.get("data", []) if item.get("name") == name]
        if len(matches) != 1:
            raise ResendReconcileError(f"Resend domain {name} must exist uniquely first")
        domain_id = matches[0].get("id")
        if not isinstance(domain_id, str):
            raise ResendReconcileError("Resend domain response has no identifier")
        return self.request("GET", f"/domains/{domain_id}")

    def keys(self) -> list[dict]:
        document = self.request("GET", "/api-keys?limit=100")
        keys = document.get("data")
        if not isinstance(keys, list):
            raise ResendReconcileError("Resend API-key inventory is invalid")
        return [key for key in keys if isinstance(key, dict)]

    def create(self, spec: ResendKeySpec, domain_id: str) -> tuple[str, str]:
        document = self.request(
            "POST",
            "/api-keys",
            {
                "name": spec.name,
                "permission": spec.permission,
                "domain_id": domain_id,
            },
        )
        key_id = document.get("id")
        token = document.get("token")
        if not isinstance(key_id, str) or not isinstance(token, str):
            raise ResendReconcileError("Resend did not return new sending-key material")
        return key_id, token

    def delete(self, key_id: str) -> None:
        self.request("DELETE", f"/api-keys/{key_id}")


class ResendKeyReconciler:
    def __init__(
        self,
        spec: ResendKeySpec,
        client: ResendClient,
        store: SopsCredentialStore,
    ):
        self.spec = spec
        self.client = client
        self.store = store

    def reconcile(self, *, apply: bool, rotate: bool) -> str:
        domain = self.client.domain(self.spec.domain)
        domain_id = domain.get("id")
        if not isinstance(domain_id, str):
            raise ResendReconcileError("Resend domain response has no identifier")
        if domain.get("status") != "verified":
            raise ResendReconcileError("Resend domain must be verified before issuing the Stalwart key")
        named = [key for key in self.client.keys() if key.get("name") == self.spec.name]
        stored = self.store.read(self.spec.output_file, self.spec.output_credential)
        if len(named) == 1 and stored is not None and not rotate:
            return f"{self.spec.name}: current"
        if not apply:
            return f"{self.spec.name}: reconciliation required"
        if (named or stored is not None) and not rotate:
            raise ResendReconcileError(
                f"{self.spec.name} has existing or partial state; inspect it and rerun with --rotate"
            )
        new_id, token = self.client.create(self.spec, domain_id)
        try:
            self.store.write(self.spec.output_file, {self.spec.output_credential: token})
        except SopsCredentialError:
            try:
                self.client.delete(new_id)
            finally:
                raise
        for key in named:
            old_id = key.get("id")
            if isinstance(old_id, str) and old_id != new_id:
                self.client.delete(old_id)
        return f"{self.spec.name}: created and encrypted"


def _string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ResendReconcileError(f"{label} must be a non-empty string")
    return value


def argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("check", "apply"))
    parser.add_argument("--repository-root", type=Path)
    parser.add_argument(
        "--rotate",
        action="store_true",
        help="create and switch to a new sending key before revoking matching old keys",
    )
    return parser


def main() -> int:
    arguments = argument_parser().parse_args()
    try:
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
        spec = ResendKeySpec.load(repository_root)
        store = SopsCredentialStore(repository_root)
        administration_key = store.read(
            spec.administration_file, spec.administration_credential
        )
        if administration_key is None:
            raise ResendReconcileError(
                f"{spec.administration_credential} must be enrolled first"
            )
        report = ResendKeyReconciler(
            spec, ResendClient(administration_key), store
        ).reconcile(apply=arguments.command == "apply", rotate=arguments.rotate)
        print(report)
        return 0
    except (
        ContractError,
        ResendReconcileError,
        SopsCredentialError,
        subprocess.CalledProcessError,
    ) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Issue the scoped Hermes service-account key directly into SOPS."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import yaml

from runtime_contract import ContractError, RuntimeContract
from sops_credentials import SopsCredentialError, SopsCredentialStore


OPENAI_CONTRACT_PATH = Path("deployments/homelab/cloud/openai-hermes.yaml")
API_BASE = "https://api.openai.com/v1"


class OpenAIReconcileError(RuntimeError):
    """A safe-to-display OpenAI reconciliation error."""


def _string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise OpenAIReconcileError(f"{label} must be a non-empty string")
    return value


def _strings(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value or not all(
        isinstance(item, str) and item for item in value
    ):
        raise OpenAIReconcileError(f"{label} must be a non-empty string list")
    return tuple(value)


def _service_account_owner_id(key: dict) -> str | None:
    owner = key.get("owner")
    if not isinstance(owner, dict) or owner.get("type") != "service_account":
        return None
    service_account = owner.get("service_account")
    if not isinstance(service_account, dict):
        return None
    identifier = service_account.get("id")
    return identifier if isinstance(identifier, str) else None


@dataclass(frozen=True)
class OpenAIKeySpec:
    project_name: str
    service_account_name: str
    key_name: str
    scopes: tuple[str, ...]
    administration_file: Path
    administration_credential: str
    administration_key_name: str
    output_file: Path
    output_credential: str
    model_ids: tuple[str, ...]
    hosted_tools: tuple[str, ...]
    hard_limit_amount: int
    hard_limit_currency: str
    hard_limit_interval: str

    @classmethod
    def load(cls, repository_root: Path) -> "OpenAIKeySpec":
        path = repository_root / OPENAI_CONTRACT_PATH
        try:
            document = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as error:
            raise OpenAIReconcileError(f"cannot read OpenAI contract {path}") from error
        if not isinstance(document, dict) or document.get("schemaVersion") != 1:
            raise OpenAIReconcileError("OpenAI contract must use schema version 1")
        project = document.get("project")
        service_account = document.get("serviceAccount")
        api_key = document.get("apiKey")
        policy = document.get("policy")
        if not all(
            isinstance(item, dict)
            for item in (project, service_account, api_key, policy)
        ):
            raise OpenAIReconcileError("OpenAI resource definitions must be mappings")
        scopes = api_key.get("scopes")
        if scopes != ["api.responses.write"]:
            raise OpenAIReconcileError(
                "Hermes OpenAI key must contain only api.responses.write"
            )
        hosted_tools = _strings(policy.get("hostedTools"), "policy.hostedTools")
        if set(hosted_tools) != {
            "code_interpreter",
            "file_search",
            "image_generation",
            "mcp",
            "web_search",
        }:
            raise OpenAIReconcileError("every OpenAI hosted tool must be denied")
        hard_limit = policy.get("hardSpendLimit")
        if not isinstance(hard_limit, dict):
            raise OpenAIReconcileError("policy.hardSpendLimit must be a mapping")
        hard_limit_amount = hard_limit.get("thresholdAmount")
        if not isinstance(hard_limit_amount, int) or hard_limit_amount <= 0:
            raise OpenAIReconcileError(
                "policy.hardSpendLimit.thresholdAmount must be positive cents"
            )

        runtime = RuntimeContract.load(repository_root)
        administration_credential = _string(
            document.get("administrationCredential"), "administrationCredential"
        )
        output_credential = _string(
            document.get("outputCredential"), "outputCredential"
        )
        administration = runtime.credential(administration_credential)
        output = runtime.provisioned_credential(output_credential)
        if administration.consumer != "openai-control-plane":
            raise OpenAIReconcileError("OpenAI Admin key has the wrong consumer")
        if output.provisioner != "reconcile-services-openai":
            raise OpenAIReconcileError("Hermes OpenAI key has the wrong provisioner")
        return cls(
            project_name=_string(project.get("name"), "project.name"),
            service_account_name=_string(
                service_account.get("name"), "serviceAccount.name"
            ),
            key_name=_string(api_key.get("name"), "apiKey.name"),
            scopes=tuple(scopes),
            administration_file=administration.secret_file,
            administration_credential=administration_credential,
            administration_key_name=_string(
                document.get("administrationKeyName"), "administrationKeyName"
            ),
            output_file=output.secret_file,
            output_credential=output_credential,
            model_ids=_strings(policy.get("modelIds"), "policy.modelIds"),
            hosted_tools=hosted_tools,
            hard_limit_amount=hard_limit_amount,
            hard_limit_currency=_string(
                hard_limit.get("currency"), "policy.hardSpendLimit.currency"
            ),
            hard_limit_interval=_string(
                hard_limit.get("interval"), "policy.hardSpendLimit.interval"
            ),
        )


class OpenAIClient:
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
                "User-Agent": "fahrican-infra-openai-key-reconciler/1.0",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                document = json.loads(response.read())
        except urllib.error.HTTPError as error:
            raise OpenAIReconcileError(
                f"OpenAI {method} {path.split('?')[0]} returned HTTP {error.code}"
            ) from error
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
            raise OpenAIReconcileError(
                f"OpenAI request {method} {path.split('?')[0]} failed"
            ) from error
        if not isinstance(document, dict):
            raise OpenAIReconcileError("OpenAI returned an invalid response")
        return document

    def paginated(self, path: str, **parameters: str) -> list[dict]:
        items: list[dict] = []
        after: str | None = None
        while True:
            query = {"limit": "100", **parameters}
            if after is not None:
                query["after"] = after
            document = self.request("GET", f"{path}?{urllib.parse.urlencode(query)}")
            page = document.get("data")
            if not isinstance(page, list):
                raise OpenAIReconcileError("OpenAI inventory response is invalid")
            items.extend(item for item in page if isinstance(item, dict))
            if document.get("has_more") is not True:
                return items
            after = document.get("last_id")
            if not isinstance(after, str) or not after:
                raise OpenAIReconcileError("OpenAI pagination response has no cursor")

    def project(self, name: str) -> dict:
        matches = [
            item
            for item in self.paginated("/organization/projects")
            if item.get("name") == name and item.get("status") == "active"
        ]
        if len(matches) != 1:
            raise OpenAIReconcileError(
                f"active OpenAI project {name} must exist uniquely first"
            )
        return matches[0]

    def service_account(self, project_id: str, name: str) -> dict:
        matches = [
            item
            for item in self.paginated(
                f"/organization/projects/{project_id}/service_accounts"
            )
            if item.get("name") == name
        ]
        if len(matches) != 1:
            raise OpenAIReconcileError(
                f"OpenAI service account {name} must exist uniquely first"
            )
        account = matches[0]
        if account.get("role") != "none":
            raise OpenAIReconcileError(
                "Hermes service account must not have a built-in project role"
            )
        return account

    def keys(self, project_id: str) -> list[dict]:
        return self.paginated(
            f"/organization/projects/{project_id}/api_keys",
            owner_project_access="any",
        )

    def model_permissions(self, project_id: str) -> dict:
        return self.request(
            "GET", f"/organization/projects/{project_id}/model_permissions"
        )

    def hosted_tool_permissions(self, project_id: str) -> dict:
        return self.request(
            "GET", f"/organization/projects/{project_id}/hosted_tool_permissions"
        )

    def hard_spend_limit(self, project_id: str) -> dict:
        return self.request("GET", f"/organization/projects/{project_id}/spend_limit")

    def administration_keys(self) -> list[dict]:
        return self.paginated("/organization/admin_api_keys")

    def delete_administration_key(self, key_id: str) -> None:
        document = self.request(
            "DELETE", f"/organization/admin_api_keys/{urllib.parse.quote(key_id)}"
        )
        if document.get("deleted") is not True:
            raise OpenAIReconcileError("OpenAI did not confirm Admin-key revocation")

    def create(self, project_id: str, service_account_id: str, spec: OpenAIKeySpec) -> str:
        document = self.request(
            "POST",
            f"/organization/projects/{project_id}/service_accounts/"
            f"{service_account_id}/api_keys",
            {"name": spec.key_name, "scopes": list(spec.scopes)},
        )
        value = document.get("value")
        if not isinstance(value, str) or not value.startswith("sk-") or len(value) < 20:
            raise OpenAIReconcileError(
                "OpenAI did not return valid service-account key material"
            )
        return value


class OpenAIKeyReconciler:
    def __init__(
        self,
        spec: OpenAIKeySpec,
        client: OpenAIClient,
        store: SopsCredentialStore,
    ):
        self.spec = spec
        self.client = client
        self.store = store

    def _inventory(self) -> tuple[str, str, list[dict], str | None]:
        project = self.client.project(self.spec.project_name)
        project_id = project.get("id")
        if not isinstance(project_id, str):
            raise OpenAIReconcileError("OpenAI project response has no identifier")
        account = self.client.service_account(
            project_id, self.spec.service_account_name
        )
        account_id = account.get("id")
        if not isinstance(account_id, str):
            raise OpenAIReconcileError("OpenAI service-account response has no identifier")
        named = [
            key
            for key in self.client.keys(project_id)
            if key.get("name") == self.spec.key_name
            and _service_account_owner_id(key) == account_id
        ]
        stored = self.store.read(self.spec.output_file, self.spec.output_credential)
        return project_id, account_id, named, stored

    def require_current(self) -> str:
        project_id, _, named, stored = self._inventory()
        if len(named) != 1 or stored is None:
            raise OpenAIReconcileError(
                "Hermes runtime key must be current before retiring administration"
            )
        if named[0].get("scopes") != list(self.spec.scopes):
            raise OpenAIReconcileError("Hermes runtime key scope metadata drifted")
        return project_id

    def reconcile(self, *, apply: bool) -> str:
        project_id, account_id, named, stored = self._inventory()
        if len(named) == 1 and stored is not None:
            return f"{self.spec.key_name}: current"
        if not apply:
            return f"{self.spec.key_name}: reconciliation required"
        if named or stored is not None:
            raise OpenAIReconcileError(
                f"{self.spec.key_name} has partial or unrecoverable state; replace the "
                "service account declaratively before issuing a new key"
            )

        value = self.client.create(project_id, account_id, self.spec)
        try:
            self.store.write(self.spec.output_file, {self.spec.output_credential: value})
        except SopsCredentialError as error:
            raise OpenAIReconcileError(
                "OpenAI issued a key but SOPS storage failed; replace the service "
                "account declaratively before retrying"
            ) from error
        return f"{self.spec.key_name}: created and encrypted"


class OpenAIPolicyVerifier:
    def __init__(self, spec: OpenAIKeySpec, client: OpenAIClient):
        self.spec = spec
        self.client = client

    def verify(self, project_id: str) -> None:
        model_permissions = self.client.model_permissions(project_id)
        model_ids = model_permissions.get("model_ids")
        if (
            model_permissions.get("mode") != "allow_list"
            or not isinstance(model_ids, list)
            or not all(isinstance(model_id, str) for model_id in model_ids)
            or set(model_ids) != set(self.spec.model_ids)
        ):
            raise OpenAIReconcileError("Hermes model allowlist is not current")

        hosted_tools = self.client.hosted_tool_permissions(project_id)
        if any(hosted_tools.get(tool) is not False for tool in self.spec.hosted_tools):
            raise OpenAIReconcileError("Hermes hosted-tool deny policy is not current")

        hard_limit = self.client.hard_spend_limit(project_id)
        if (
            hard_limit.get("threshold_amount") != self.spec.hard_limit_amount
            or hard_limit.get("currency") != self.spec.hard_limit_currency
            or hard_limit.get("interval") != self.spec.hard_limit_interval
        ):
            raise OpenAIReconcileError("Hermes monthly hard spend limit is not current")


class OpenAIAdminRetirer:
    def __init__(
        self,
        spec: OpenAIKeySpec,
        client: OpenAIClient,
        store: SopsCredentialStore,
    ):
        self.spec = spec
        self.client = client
        self.store = store

    def retire(self) -> str:
        project_id = OpenAIKeyReconciler(
            self.spec, self.client, self.store
        ).require_current()
        OpenAIPolicyVerifier(self.spec, self.client).verify(project_id)
        matches = [
            key
            for key in self.client.administration_keys()
            if key.get("name") == self.spec.administration_key_name
        ]
        if len(matches) != 1:
            raise OpenAIReconcileError(
                f"Admin key {self.spec.administration_key_name} must exist uniquely"
            )
        key_id = matches[0].get("id")
        if not isinstance(key_id, str) or not key_id:
            raise OpenAIReconcileError("OpenAI Admin-key response has no identifier")
        self.client.delete_administration_key(key_id)
        try:
            self.store.remove(
                self.spec.administration_file, self.spec.administration_credential
            )
        except SopsCredentialError as error:
            raise OpenAIReconcileError(
                "Admin key was revoked but local ciphertext removal failed"
            ) from error
        return f"{self.spec.administration_key_name}: revoked and ciphertext removed"


def argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("check", "apply", "retire-admin"))
    parser.add_argument("--repository-root", type=Path)
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
        spec = OpenAIKeySpec.load(repository_root)
        store = SopsCredentialStore(repository_root)
        administration_key = store.read(
            spec.administration_file, spec.administration_credential
        )
        if administration_key is None:
            raise OpenAIReconcileError(
                f"{spec.administration_credential} must be enrolled first"
            )
        client = OpenAIClient(administration_key)
        if arguments.command == "retire-admin":
            report = OpenAIAdminRetirer(spec, client, store).retire()
        else:
            report = OpenAIKeyReconciler(spec, client, store).reconcile(
                apply=arguments.command == "apply"
            )
        print(report)
        return 0
    except (
        ContractError,
        OpenAIReconcileError,
        SopsCredentialError,
        subprocess.CalledProcessError,
    ) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Move AWS mail credentials across narrow, no-echo runtime boundaries."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

from runtime_contract import RuntimeContract
from sops_credentials import SopsCredentialError, SopsCredentialStore


AUTH_CONSUMER = "aws-mail-auth"
AUTH_PROVISIONER = "enroll-aws-mail-auth"
AUTH_KEYS = ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY")
BOOTSTRAP_KEYS = (
    "AWS_BOOTSTRAP_ACCESS_KEY_ID",
    "AWS_BOOTSTRAP_SECRET_ACCESS_KEY",
)
AUTH_INTAKE = Path("secrets")
GITOPS_USER = "fahrican-mail-gitops"
GITOPS_POLICY = "fahrican-mail-gitops"
GITOPS_POLICY_FILE = Path(
    "components/cloud/services/mail-aws/bootstrap-iam-policy.json"
)
RESEND_FILE = Path("deployments/homelab/cloud/host-runtime/mail-edge.sops.yaml")
RESEND_KEY = "STALWART_RESEND_API_KEY"
RESEND_SECRET_ID = "fahrican/stalwart/resend"
AWS_REGION = "eu-central-1"


class AwsMailCredentialError(RuntimeError):
    """A credential error whose message is safe to display."""


@dataclass(frozen=True)
class ProvisioningIdentity:
    """Verified identities needed to complete or resume one enrollment."""

    credentials: dict[str, str]
    bootstrap_user: str
    created: bool


class IntakeFiles:
    """Hold validated descriptors so enrollment cannot follow a replaced path."""

    def __init__(self, repository_root: Path):
        self.repository_root = repository_root
        self.descriptors: dict[str, int] = {}

    def __enter__(self) -> "IntakeFiles":
        try:
            for key in BOOTSTRAP_KEYS:
                relative_path = AUTH_INTAKE / f"{key}.key"
                path = self.repository_root / relative_path
                descriptor = os.open(path, os.O_RDWR | os.O_NOFOLLOW)
                metadata = os.fstat(descriptor)
                if not stat.S_ISREG(metadata.st_mode):
                    raise AwsMailCredentialError(
                        f"{relative_path} must be a regular file"
                    )
                if stat.S_IMODE(metadata.st_mode) != 0o600:
                    raise AwsMailCredentialError(f"{relative_path} must use mode 0600")
                if metadata.st_uid != os.getuid():
                    raise AwsMailCredentialError(
                        f"{relative_path} must be owned by the current user"
                    )
                self.descriptors[key] = descriptor
            return self
        except (OSError, AwsMailCredentialError):
            self.__exit__(None, None, None)
            raise

    def __exit__(self, *_: object) -> None:
        for descriptor in self.descriptors.values():
            os.close(descriptor)
        self.descriptors.clear()

    def values(self) -> dict[str, str]:
        values: dict[str, str] = {}
        for key, descriptor in self.descriptors.items():
            os.lseek(descriptor, 0, os.SEEK_SET)
            raw = os.read(descriptor, 4097)
            if len(raw) > 4096:
                raise AwsMailCredentialError(f"{key} intake is unexpectedly large")
            try:
                value = raw.decode("ascii").strip()
            except UnicodeDecodeError as error:
                raise AwsMailCredentialError(f"{key} intake is not ASCII") from error
            if not value or any(character.isspace() for character in value):
                raise AwsMailCredentialError(f"{key} intake is empty or malformed")
            values[key] = value
        if not re.fullmatch(r"(?:AKIA|ASIA)[A-Z0-9]{16}", values[BOOTSTRAP_KEYS[0]]):
            raise AwsMailCredentialError("AWS bootstrap access key ID has an invalid format")
        if not re.fullmatch(r"[A-Za-z0-9/+=]{40}", values[BOOTSTRAP_KEYS[1]]):
            raise AwsMailCredentialError("AWS bootstrap secret access key has an invalid format")
        return values

    def clear(self) -> None:
        for descriptor in self.descriptors.values():
            os.ftruncate(descriptor, 0)
            os.fsync(descriptor)


class AwsMailCredentials:
    def __init__(self, repository_root: Path):
        self.repository_root = repository_root.resolve()
        self.contract = RuntimeContract.load(self.repository_root)
        self.store = SopsCredentialStore(self.repository_root)

    @staticmethod
    def _aws_environment(values: dict[str, str]) -> dict[str, str]:
        environment = os.environ.copy()
        environment.update(
            {
                "AWS_ACCESS_KEY_ID": values[BOOTSTRAP_KEYS[0]],
                "AWS_SECRET_ACCESS_KEY": values[BOOTSTRAP_KEYS[1]],
                "AWS_DEFAULT_REGION": AWS_REGION,
            }
        )
        environment.pop("AWS_SESSION_TOKEN", None)
        return environment

    @staticmethod
    def _aws(
        arguments: list[str],
        environment: dict[str, str],
        *,
        capture: bool = False,
        input_document: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["aws", *arguments],
            check=False,
            input=json.dumps(input_document) if input_document is not None else None,
            stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
            env=environment,
        )

    def _caller_identity(
        self, environment: dict[str, str], description: str
    ) -> tuple[str, str]:
        identity = self._aws(
            ["sts", "get-caller-identity", "--output", "json"],
            environment,
            capture=True,
        )
        if identity.returncode != 0:
            raise AwsMailCredentialError(f"AWS rejected the {description}")
        try:
            document = json.loads(identity.stdout)
            account_id = str(document["Account"])
            arn = str(document["Arn"])
        except (json.JSONDecodeError, KeyError, TypeError) as error:
            raise AwsMailCredentialError("AWS returned an invalid account identity") from error
        if not re.fullmatch(r"[0-9]{12}", account_id):
            raise AwsMailCredentialError("AWS returned an invalid account identifier")
        return account_id, arn

    def _bootstrap_user(
        self, environment: dict[str, str], caller_arn: str
    ) -> str:
        current_user = self._aws(
            ["iam", "get-user", "--output", "json"],
            environment,
            capture=True,
        )
        if current_user.returncode != 0:
            raise AwsMailCredentialError(
                "the temporary AWS credential must belong to an IAM user"
            )
        try:
            user = json.loads(current_user.stdout)["User"]
            username = str(user["UserName"])
            user_arn = str(user["Arn"])
        except (json.JSONDecodeError, KeyError, TypeError) as error:
            raise AwsMailCredentialError("AWS returned an invalid bootstrap user") from error
        if user_arn != caller_arn or not username:
            raise AwsMailCredentialError("AWS returned an inconsistent bootstrap user")
        return username

    def _verify_gitops_identity(
        self, values: dict[str, str], account_id: str
    ) -> None:
        environment = os.environ.copy()
        environment.update(values)
        environment["AWS_DEFAULT_REGION"] = AWS_REGION
        environment.pop("AWS_SESSION_TOKEN", None)
        verified_account, arn = self._caller_identity(
            environment, "dedicated mail GitOps pair"
        )
        if (
            verified_account != account_id
            or arn != f"arn:aws:iam::{account_id}:user/{GITOPS_USER}"
        ):
            raise AwsMailCredentialError(
                "the generated AWS pair does not belong to the dedicated mail GitOps identity"
            )

    def _reconcile_gitops_identity(
        self, bootstrap: dict[str, str], destination: Path
    ) -> ProvisioningIdentity:
        environment = self._aws_environment(bootstrap)
        account_id, bootstrap_arn = self._caller_identity(
            environment, "temporary bootstrap pair"
        )
        bootstrap_user = self._bootstrap_user(environment, bootstrap_arn)

        get_user = self._aws(
            ["iam", "get-user", "--user-name", GITOPS_USER], environment
        )
        if get_user.returncode != 0:
            created = self._aws(
                ["iam", "create-user", "--user-name", GITOPS_USER], environment
            )
            if created.returncode != 0:
                raise AwsMailCredentialError(
                    "AWS could not create the dedicated mail GitOps identity"
                )

        try:
            policy_template = (
                self.repository_root / GITOPS_POLICY_FILE
            ).read_text(encoding="utf-8")
            policy = policy_template.replace("ACCOUNT_ID", account_id)
            json.loads(policy)
        except (OSError, json.JSONDecodeError) as error:
            raise AwsMailCredentialError("the AWS mail IAM policy is invalid") from error
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", prefix="aws-mail-policy-"
        ) as policy_file:
            policy_file.write(policy)
            policy_file.flush()
            reconciled = self._aws(
                [
                    "iam",
                    "put-user-policy",
                    "--user-name",
                    GITOPS_USER,
                    "--policy-name",
                    GITOPS_POLICY,
                    "--policy-document",
                    f"file://{policy_file.name}",
                ],
                environment,
            )
        if reconciled.returncode != 0:
            raise AwsMailCredentialError(
                "AWS could not reconcile the dedicated mail GitOps policy"
            )

        existing = self._aws(
            [
                "iam",
                "list-access-keys",
                "--user-name",
                GITOPS_USER,
                "--output",
                "json",
            ],
            environment,
            capture=True,
        )
        if existing.returncode != 0:
            raise AwsMailCredentialError("AWS could not inspect the mail GitOps keys")
        try:
            inventory = json.loads(existing.stdout)["AccessKeyMetadata"]
        except (json.JSONDecodeError, KeyError, TypeError) as error:
            raise AwsMailCredentialError("AWS returned an invalid access-key inventory") from error
        if inventory:
            stored = {key: self.store.read(destination, key) for key in AUTH_KEYS}
            if (
                len(inventory) == 1
                and all(stored.values())
                and inventory[0].get("AccessKeyId") == stored[AUTH_KEYS[0]]
            ):
                values = {key: str(stored[key]) for key in AUTH_KEYS}
                self._verify_gitops_identity(values, account_id)
                return ProvisioningIdentity(values, bootstrap_user, False)
            raise AwsMailCredentialError(
                "the dedicated mail GitOps identity already has an unrecoverable key; "
                "review and delete it before enrollment"
            )

        created_key = self._aws(
            [
                "iam",
                "create-access-key",
                "--user-name",
                GITOPS_USER,
                "--output",
                "json",
            ],
            environment,
            capture=True,
        )
        if created_key.returncode != 0:
            raise AwsMailCredentialError("AWS could not create the mail GitOps key")
        try:
            document = json.loads(created_key.stdout)["AccessKey"]
            values = {
                AUTH_KEYS[0]: document["AccessKeyId"],
                AUTH_KEYS[1]: document["SecretAccessKey"],
            }
        except (json.JSONDecodeError, KeyError, TypeError) as error:
            raise AwsMailCredentialError("AWS returned an invalid access key") from error
        try:
            self._verify_gitops_identity(values, account_id)
        except AwsMailCredentialError:
            self._delete_gitops_key(values[AUTH_KEYS[0]], bootstrap)
            raise
        return ProvisioningIdentity(values, bootstrap_user, True)

    def _delete_gitops_key(
        self, access_key_id: str, bootstrap: dict[str, str]
    ) -> None:
        self._aws(
            [
                "iam",
                "delete-access-key",
                "--cli-input-json",
                "file:///dev/stdin",
            ],
            self._aws_environment(bootstrap),
            input_document={
                "UserName": GITOPS_USER,
                "AccessKeyId": access_key_id,
            },
        )

    def _revoke_bootstrap_key(
        self, bootstrap_user: str, bootstrap: dict[str, str]
    ) -> None:
        revoked = self._aws(
            ["iam", "delete-access-key", "--cli-input-json", "file:///dev/stdin"],
            self._aws_environment(bootstrap),
            input_document={
                "UserName": bootstrap_user,
                "AccessKeyId": bootstrap[BOOTSTRAP_KEYS[0]],
            },
        )
        if revoked.returncode != 0:
            raise AwsMailCredentialError(
                "AWS could not revoke the temporary bootstrap key; intake files were preserved"
            )

    def enroll_provisioning(self) -> None:
        routed = {
            credential.name: credential
            for credential in self.contract.provisioned
            if credential.consumer == AUTH_CONSUMER
        }
        if tuple(routed) != AUTH_KEYS or any(
            item.provisioner != AUTH_PROVISIONER for item in routed.values()
        ):
            raise AwsMailCredentialError(
                "the AWS mail provisioning contract does not match the enrollment interface"
            )
        destinations = {item.secret_file for item in routed.values()}
        if len(destinations) != 1:
            raise AwsMailCredentialError(
                "AWS provisioning credentials must share one SOPS destination"
            )
        destination = destinations.pop()
        with IntakeFiles(self.repository_root) as intake:
            bootstrap = intake.values()
            identity = self._reconcile_gitops_identity(bootstrap, destination)
            if identity.created:
                try:
                    self.store.write(destination, identity.credentials)
                except SopsCredentialError:
                    self._delete_gitops_key(
                        identity.credentials[AUTH_KEYS[0]], bootstrap
                    )
                    raise
            self._revoke_bootstrap_key(identity.bootstrap_user, bootstrap)
            intake.clear()

    def publish_resend(self) -> None:
        auth = {
            key: self.store.read(
                self.contract.provisioned_credential(key).secret_file, key
            )
            for key in AUTH_KEYS
        }
        resend = self.store.read(RESEND_FILE, RESEND_KEY)
        if any(not value for value in auth.values()) or not resend:
            raise AwsMailCredentialError(
                "AWS provisioning or Resend ciphertext is not enrolled"
            )
        environment = os.environ.copy()
        environment.update({key: value for key, value in auth.items() if value})
        result = subprocess.run(
            [
                "aws",
                "secretsmanager",
                "put-secret-value",
                "--region",
                AWS_REGION,
                "--secret-id",
                RESEND_SECRET_ID,
                "--secret-string",
                "file:///dev/stdin",
            ],
            input=resend,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
            check=False,
            env=environment,
        )
        if result.returncode != 0:
            raise AwsMailCredentialError(
                "AWS rejected the Resend secret publication; no value was displayed"
            )


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("provisioning", "resend"))
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    return parser.parse_args()


def main() -> int:
    arguments = parse_arguments()
    try:
        credentials = AwsMailCredentials(arguments.repository_root)
        if arguments.action == "provisioning":
            credentials.enroll_provisioning()
            message = (
                "AWS mail provisioning credentials enrolled; temporary key revoked "
                "and intake files cleared."
            )
        else:
            credentials.publish_resend()
            message = "AWS mail Resend credential published without displaying it."
    except (AwsMailCredentialError, SopsCredentialError, OSError) as error:
        print(str(error), file=sys.stderr)
        return 1
    print(message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

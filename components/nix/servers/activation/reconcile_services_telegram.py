#!/usr/bin/env python3
"""Reconcile Telegram bot metadata and discover declared private chat targets."""

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


TELEGRAM_CONTRACT_PATH = Path("deployments/homelab/cloud/telegram-bots.yaml")


class TelegramReconcileError(RuntimeError):
    """A safe-to-display Telegram reconciliation error."""


@dataclass(frozen=True)
class BotSpec:
    identifier: str
    name: str
    username: str
    description: str
    short_description: str
    token_file: Path
    token_credential: str
    command: str
    chat_type: str
    chat_title: str | None
    output_file: Path
    chat_credential: str
    allowed_users_credential: str | None


class TelegramContract:
    def __init__(self, bots: tuple[BotSpec, ...]):
        self.bots = bots

    @classmethod
    def load(cls, repository_root: Path) -> "TelegramContract":
        path = repository_root / TELEGRAM_CONTRACT_PATH
        try:
            document = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as error:
            raise TelegramReconcileError(f"cannot read Telegram contract {path}") from error
        if not isinstance(document, dict) or document.get("schemaVersion") != 1:
            raise TelegramReconcileError("Telegram contract must use schema version 1")
        definitions = document.get("bots")
        if not isinstance(definitions, dict) or set(definitions) != {
            "infrastructure",
            "hermes",
            "media",
        }:
            raise TelegramReconcileError("Telegram contract must declare the three service bots")
        runtime = RuntimeContract.load(repository_root)
        bots: list[BotSpec] = []
        for identifier, value in definitions.items():
            definition = _mapping(value, f"bots.{identifier}")
            activation = _mapping(definition.get("activation"), f"bots.{identifier}.activation")
            outputs = _mapping(definition.get("outputs"), f"bots.{identifier}.outputs")
            token_credential = _string(
                definition.get("tokenCredential"), f"bots.{identifier}.tokenCredential"
            )
            chat_credential = _string(
                outputs.get("chatCredential"), f"bots.{identifier}.outputs.chatCredential"
            )
            allowed = outputs.get("allowedUsersCredential")
            if allowed is not None:
                allowed = _string(allowed, f"bots.{identifier}.outputs.allowedUsersCredential")
            token_route = runtime.credential(token_credential)
            chat_route = runtime.provisioned_credential(chat_credential)
            if chat_route.provisioner != "reconcile-services-telegram":
                raise TelegramReconcileError(f"wrong provisioner for {chat_credential}")
            if allowed is not None:
                allowed_route = runtime.provisioned_credential(allowed)
                if allowed_route.provisioner != "reconcile-services-telegram":
                    raise TelegramReconcileError(f"wrong provisioner for {allowed}")
                if allowed_route.secret_file != chat_route.secret_file:
                    raise TelegramReconcileError(f"Telegram outputs for {identifier} must be co-located")
            chat_type = _string(
                activation.get("chatType"), f"bots.{identifier}.activation.chatType"
            )
            if chat_type not in {"private", "group"}:
                raise TelegramReconcileError(f"invalid chat type for {identifier}")
            chat_title = activation.get("chatTitle")
            if chat_type == "group":
                chat_title = _string(chat_title, f"bots.{identifier}.activation.chatTitle")
            elif chat_title is not None:
                raise TelegramReconcileError(f"private bot {identifier} cannot select a group title")
            bots.append(
                BotSpec(
                    identifier=identifier,
                    name=_bounded_string(definition.get("name"), f"bots.{identifier}.name", 64),
                    username=_username(definition.get("username"), identifier),
                    description=_bounded_string(
                        definition.get("description"), f"bots.{identifier}.description", 512
                    ),
                    short_description=_bounded_string(
                        definition.get("shortDescription"),
                        f"bots.{identifier}.shortDescription",
                        120,
                    ),
                    token_file=token_route.secret_file,
                    token_credential=token_credential,
                    command=_command(activation.get("command"), identifier),
                    chat_type=chat_type,
                    chat_title=chat_title,
                    output_file=chat_route.secret_file,
                    chat_credential=chat_credential,
                    allowed_users_credential=allowed,
                )
            )
        if len({bot.username for bot in bots}) != len(bots):
            raise TelegramReconcileError("Telegram usernames must be unique")
        return cls(tuple(bots))


class TelegramClient:
    def __init__(self, token: str):
        self.base_url = f"https://api.telegram.org/bot{token}/"

    def call(self, method: str, payload: dict | None = None) -> object:
        request = urllib.request.Request(
            self.base_url + method,
            data=json.dumps(payload or {}).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                document = json.load(response)
        except urllib.error.HTTPError as error:
            raise TelegramReconcileError(
                f"Telegram rejected {method} with HTTP {error.code}"
            ) from error
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
            raise TelegramReconcileError(f"Telegram request {method} failed") from error
        if not isinstance(document, dict) or document.get("ok") is not True:
            raise TelegramReconcileError(f"Telegram request {method} was not accepted")
        return document.get("result")

    def metadata(self) -> dict:
        result = self.call("getMe")
        if not isinstance(result, dict):
            raise TelegramReconcileError("Telegram getMe response is invalid")
        return result

    def configure(self, spec: BotSpec) -> None:
        for method, payload in (
            ("setMyName", {"name": spec.name}),
            ("setMyDescription", {"description": spec.description}),
            ("setMyShortDescription", {"short_description": spec.short_description}),
            ("deleteMyCommands", {}),
        ):
            if self.call(method, payload) is not True:
                raise TelegramReconcileError(f"Telegram did not apply {method} for {spec.identifier}")

    def updates(self) -> list[dict]:
        result = self.call("getUpdates", {"allowed_updates": ["message"]})
        if not isinstance(result, list):
            raise TelegramReconcileError("Telegram getUpdates response is invalid")
        return [update for update in result if isinstance(update, dict)]

    def acknowledge(self, update_id: int) -> None:
        self.call("getUpdates", {"offset": update_id + 1, "allowed_updates": ["message"]})


class TelegramReconciler:
    def __init__(self, contract: TelegramContract, store: SopsCredentialStore):
        self.contract = contract
        self.store = store

    def reconcile(self, *, apply: bool, rediscover: bool) -> list[str]:
        reports: list[str] = []
        for spec in self.contract.bots:
            token = self.store.read(spec.token_file, spec.token_credential)
            if token is None:
                raise TelegramReconcileError(
                    f"{spec.token_credential} must be enrolled before Telegram reconciliation"
                )
            client = TelegramClient(token)
            metadata = client.metadata()
            if metadata.get("username") != spec.username:
                raise TelegramReconcileError(
                    f"{spec.identifier} bot username must be @{spec.username}"
                )
            if apply:
                client.configure(spec)
            stored_chat = self.store.read(spec.output_file, spec.chat_credential)
            stored_allowed = (
                self.store.read(spec.output_file, spec.allowed_users_credential)
                if spec.allowed_users_credential
                else "not-required"
            )
            if stored_chat is not None and stored_allowed is not None and not rediscover:
                reports.append(f"@{spec.username}: metadata {'applied' if apply else 'reachable'}, target current")
                continue
            if not apply:
                reports.append(f"@{spec.username}: activation message required")
                continue
            update_id, chat_id, user_id = _select_activation(spec, client.updates())
            values = {spec.chat_credential: str(chat_id)}
            if spec.allowed_users_credential:
                values[spec.allowed_users_credential] = str(user_id)
            self.store.write(spec.output_file, values)
            client.acknowledge(update_id)
            reports.append(f"@{spec.username}: metadata applied, target discovered and encrypted")
        return reports


def _select_activation(spec: BotSpec, updates: list[dict]) -> tuple[int, int, int]:
    matches: list[tuple[int, int, int]] = []
    accepted_commands = {spec.command, f"{spec.command}@{spec.username}"}
    for update in updates:
        message = update.get("message")
        if not isinstance(message, dict) or message.get("text") not in accepted_commands:
            continue
        chat = message.get("chat")
        sender = message.get("from")
        update_id = update.get("update_id")
        if not isinstance(chat, dict) or not isinstance(sender, dict) or not isinstance(update_id, int):
            continue
        actual_type = chat.get("type")
        if spec.chat_type == "group" and actual_type not in {"group", "supergroup"}:
            continue
        if spec.chat_type == "private" and actual_type != "private":
            continue
        if spec.chat_title is not None and chat.get("title") != spec.chat_title:
            continue
        chat_id = chat.get("id")
        user_id = sender.get("id")
        if isinstance(chat_id, int) and isinstance(user_id, int):
            matches.append((update_id, chat_id, user_id))
    if len(matches) != 1:
        raise TelegramReconcileError(
            f"expected exactly one matching {spec.command} update for @{spec.username}; found {len(matches)}"
        )
    return matches[0]


def _mapping(value: object, label: str) -> dict:
    if not isinstance(value, dict):
        raise TelegramReconcileError(f"{label} must be a mapping")
    return value


def _string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise TelegramReconcileError(f"{label} must be a non-empty string")
    return value


def _bounded_string(value: object, label: str, maximum: int) -> str:
    result = _string(value, label)
    if len(result) > maximum:
        raise TelegramReconcileError(f"{label} exceeds Telegram's {maximum}-character limit")
    return result


def _username(value: object, identifier: str) -> str:
    username = _string(value, f"bots.{identifier}.username")
    if not username.endswith("_bot") or not username.replace("_", "").isalnum():
        raise TelegramReconcileError(f"invalid Telegram username for {identifier}")
    return username


def _command(value: object, identifier: str) -> str:
    command = _string(value, f"bots.{identifier}.activation.command")
    if not command.startswith("/") or not command[1:].replace("_", "").isalnum():
        raise TelegramReconcileError(f"invalid activation command for {identifier}")
    return command


def argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("check", "apply"))
    parser.add_argument("--repository-root", type=Path)
    parser.add_argument(
        "--rediscover",
        action="store_true",
        help="replace previously encrypted target IDs from fresh activation messages",
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
        contract = TelegramContract.load(repository_root)
        reports = TelegramReconciler(
            contract, SopsCredentialStore(repository_root)
        ).reconcile(apply=arguments.command == "apply", rediscover=arguments.rediscover)
        for report in reports:
            print(report)
        return 0
    except (
        ContractError,
        SopsCredentialError,
        TelegramReconcileError,
        subprocess.CalledProcessError,
    ) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

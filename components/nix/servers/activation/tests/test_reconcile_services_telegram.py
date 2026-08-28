from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import yaml

from reconcile_services_telegram import (
    TELEGRAM_CONTRACT_PATH,
    BotSpec,
    TelegramContract,
    TelegramReconcileError,
    _select_activation,
)
from runtime_contract import CONTRACT_PATH


def bot_spec(chat_type: str = "private") -> BotSpec:
    return BotSpec(
        identifier="service",
        name="Fahrican Service",
        username="fahrican_service_bot",
        description="Private service bot.",
        short_description="Private service bot.",
        token_file=Path("service.sops.yaml"),
        token_credential="SERVICE_TELEGRAM_BOT_TOKEN",
        command="/activate",
        chat_type=chat_type,
        chat_title="Fahrican Infra Alerts" if chat_type == "group" else None,
        output_file=Path("service.sops.yaml"),
        chat_credential="SERVICE_TELEGRAM_HOME_CHANNEL",
        allowed_users_credential="SERVICE_TELEGRAM_ALLOWED_USERS",
    )


class TelegramActivationSelectionTest(unittest.TestCase):
    def test_contract_accepts_a_declaratively_named_bot(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            runtime_path = root / CONTRACT_PATH
            runtime_path.parent.mkdir(parents=True)
            runtime = {
                "schemaVersion": 9,
                "secretFile": "runtime.sops.yaml",
                "credentials": {"telegram": ["SERVICE_TELEGRAM_BOT_TOKEN"]},
                "generatedSecrets": {
                    "local": {
                        "secretFile": "generated.sops.yaml",
                        "keys": ["GENERATED_KEY"],
                    }
                },
                "provisionedSecrets": {
                    "telegram-service": {
                        "provisioner": "reconcile-services-telegram",
                        "secretFile": "runtime.sops.yaml",
                        "keys": [
                            "SERVICE_TELEGRAM_CHAT_ID",
                            "SERVICE_TELEGRAM_ALLOWED_USERS",
                        ],
                    }
                },
            }
            runtime_path.write_text(
                yaml.safe_dump(
                    {"data": {"required-keys.yaml": yaml.safe_dump(runtime)}}
                ),
                encoding="utf-8",
            )
            telegram_path = root / TELEGRAM_CONTRACT_PATH
            telegram_path.parent.mkdir(parents=True, exist_ok=True)
            telegram_path.write_text(
                yaml.safe_dump(
                    {
                        "schemaVersion": 1,
                        "bots": {
                            "service": {
                                "name": "Fahrican Service",
                                "username": "fahrican_service_bot",
                                "description": "Private service bot.",
                                "shortDescription": "Private service bot.",
                                "tokenCredential": "SERVICE_TELEGRAM_BOT_TOKEN",
                                "activation": {
                                    "command": "/activate",
                                    "chatType": "private",
                                },
                                "outputs": {
                                    "chatCredential": "SERVICE_TELEGRAM_CHAT_ID",
                                    "allowedUsersCredential": (
                                        "SERVICE_TELEGRAM_ALLOWED_USERS"
                                    ),
                                },
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            contract = TelegramContract.load(root)

        self.assertEqual([bot.identifier for bot in contract.bots], ["service"])

    def test_selects_one_declared_private_activation_without_exposing_content(self) -> None:
        update = {
            "update_id": 17,
            "message": {
                "text": "/activate",
                "chat": {"id": 101, "type": "private"},
                "from": {"id": 202},
            },
        }
        self.assertEqual(_select_activation(bot_spec(), [update]), (17, 101, 202))

    def test_rejects_ambiguous_activation_messages(self) -> None:
        update = {
            "update_id": 17,
            "message": {
                "text": "/activate",
                "chat": {"id": 101, "type": "private"},
                "from": {"id": 202},
            },
        }
        with self.assertRaisesRegex(TelegramReconcileError, "exactly one"):
            _select_activation(bot_spec(), [update, {**update, "update_id": 18}])

    def test_group_activation_requires_exact_declared_title(self) -> None:
        update = {
            "update_id": 17,
            "message": {
                "text": "/activate",
                "chat": {"id": -101, "type": "supergroup", "title": "Wrong"},
                "from": {"id": 202},
            },
        }
        with self.assertRaisesRegex(TelegramReconcileError, "found 0"):
            _select_activation(bot_spec("group"), [update])


if __name__ == "__main__":
    unittest.main()

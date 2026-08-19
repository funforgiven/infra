from pathlib import Path
import unittest

from reconcile_services_telegram import BotSpec, TelegramReconcileError, _select_activation


def bot_spec(chat_type: str = "private") -> BotSpec:
    return BotSpec(
        identifier="hermes",
        name="Fahrican Hermes",
        username="fahrican_hermes_bot",
        description="Private assistant.",
        short_description="Private assistant.",
        token_file=Path("hermes.sops.yaml"),
        token_credential="HERMES_TELEGRAM_BOT_TOKEN",
        command="/activate",
        chat_type=chat_type,
        chat_title="Fahrican Infra Alerts" if chat_type == "group" else None,
        output_file=Path("hermes.sops.yaml"),
        chat_credential="HERMES_TELEGRAM_HOME_CHANNEL",
        allowed_users_credential="HERMES_TELEGRAM_ALLOWED_USERS",
    )


class TelegramActivationSelectionTest(unittest.TestCase):
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

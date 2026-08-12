from __future__ import annotations

import inspect
import json
import os
import unittest
from pathlib import Path

import yaml

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
AUTOMATION_ROOT = REPOSITORY_ROOT / "components/cloud/network-automation"
LOCAL_COLLECTIONS_PATH = AUTOMATION_ROOT / "collections"
LOCAL_COLLECTION_ROOT = (
    LOCAL_COLLECTIONS_PATH / "ansible_collections/fahrican/routeros"
)
LOCAL_GALAXY_PATH = LOCAL_COLLECTION_ROOT / "galaxy.yml"

# The source-local terminal plugin is part of this component's executable
# contract.  Make the test self-contained instead of depending on a caller's
# shell environment or an already-installed collection.
existing_collections_path = os.environ.get("ANSIBLE_COLLECTIONS_PATH")
os.environ["ANSIBLE_COLLECTIONS_PATH"] = str(LOCAL_COLLECTIONS_PATH) + (
    f":{existing_collections_path}" if existing_collections_path else ""
)

from ansible import release as ansible_release
from ansible.plugins.loader import cliconf_loader, init_plugin_loader, terminal_loader


class Shell:
    def __init__(self) -> None:
        self.sent: list[bytes] = []

    def sendall(self, data: bytes) -> None:
        self.sent.append(data)


class Connection:
    def __init__(self) -> None:
        self._ssh_shell = Shell()
        self._handle_prompt = self.original_handle_prompt
        self._strip = self.original_strip

    @staticmethod
    def original_handle_prompt(*args, **kwargs):
        return "upstream"

    @staticmethod
    def original_strip(data):
        return data

    @staticmethod
    def get_prompt() -> bytes:
        return b"[admin@router] >"

    @staticmethod
    def exec_command(command):
        raise AssertionError(command)


class RouterOSTerminalTransportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        init_plugin_loader()

    @staticmethod
    def make_terminal():
        connection = Connection()
        terminal = terminal_loader.get(
            "fahrican.routeros.routeros",
            connection,
        )
        if terminal is None:
            raise AssertionError("source-local RouterOS terminal did not load")
        return connection, terminal

    def test_loader_selects_local_terminal_and_upstream_cliconf(self) -> None:
        connection, terminal = self.make_terminal()
        self.assertTrue(
            Path(terminal._original_path).is_relative_to(LOCAL_COLLECTION_ROOT)
        )

        cliconf = cliconf_loader.get("fahrican.routeros.routeros", connection)
        self.assertIsNotNone(cliconf)
        self.assertEqual("community.routeros.routeros", cliconf.ansible_name)
        self.assertIn("fahrican.routeros.routeros", cliconf.ansible_aliases)

    def test_answers_both_queries_in_observed_order_without_cr(self) -> None:
        cases = (
            (b"\x1bZxxx\x1b[6n", [b"\x1b/Z", b"\x1b[1;1R"]),
            (b"\x1b[6nxxx\x1bZ", [b"\x1b[1;1R", b"\x1b/Z"]),
        )
        for transcript, expected in cases:
            with self.subTest(transcript=transcript):
                connection, _terminal = self.make_terminal()
                self.assertEqual(b"xxx", connection._strip(transcript))
                self.assertEqual(expected, connection._ssh_shell.sent)

    def test_answers_queries_split_across_command_receive_windows(self) -> None:
        connection, _terminal = self.make_terminal()
        self.assertEqual(b"banner", connection._strip(b"banner\x1b["))
        self.assertEqual(b"xxx", connection._strip(b"6nxxx\x1bZ"))
        self.assertEqual(
            [b"\x1b[1;1R", b"\x1b/Z"],
            connection._ssh_shell.sent,
        )

    def test_query_hook_runs_when_a_command_has_no_prompt_list(self) -> None:
        connection, _terminal = self.make_terminal()
        self.assertEqual(
            b"command output\r\n[admin@router] >",
            connection._strip(
                b"command output\x1b[6n\r\n[admin@router] >"
            ),
        )
        self.assertEqual([b"\x1b[1;1R"], connection._ssh_shell.sent)

    def test_preserves_cursor_query_while_stripping_other_csi(self) -> None:
        _connection, terminal = self.make_terminal()
        data = b"\x1b[31mred\x1b[0m\x1b[6n"
        for regex in terminal.ansi_re:
            data = regex.sub(b"", data)
        self.assertEqual(b"red\x1b[6n", data)

    def test_keeps_query_hook_after_initial_login_and_restores_on_close(self) -> None:
        connection, terminal = self.make_terminal()
        terminal.on_open_shell()
        self.assertEqual(b"", connection._strip(b"\x1b[6n"))
        self.assertEqual([b"\x1b[1;1R"], connection._ssh_shell.sent)
        terminal.on_close_shell()
        self.assertIs(connection._strip, terminal._upstream_strip)

    def test_private_network_cli_hook_signature_is_pinned(self) -> None:
        from ansible_collections.ansible.netcommon.plugins.connection.network_cli import (
            Connection as NetcommonNetworkCLIConnection,
        )

        parameters = list(
            inspect.signature(
                NetcommonNetworkCLIConnection._handle_prompt
            ).parameters
        )
        self.assertEqual(
            [
                "self",
                "resp",
                "prompts",
                "answer",
                "newline",
                "prompt_retry_check",
                "check_all",
            ],
            parameters,
        )

    def test_upstream_routeros_ansi_contract_is_pinned(self) -> None:
        from ansible_collections.community.routeros.plugins.terminal.routeros import (
            TerminalModule as CommunityRouterOSTerminalModule,
        )

        self.assertEqual(
            [
                br"(\x1b\[\?1h\x1b=)",
                (
                    br"((?:\x9b|\x1b\x5b)[\x30-\x3f]*"
                    br"[\x20-\x2f]*[\x40-\x7e])"
                ),
                br"\x08.",
            ],
            [pattern.pattern for pattern in CommunityRouterOSTerminalModule.ansi_re],
        )

    def test_declared_collection_versions_match_nix_runtime(self) -> None:
        declared = yaml.safe_load(
            LOCAL_GALAXY_PATH.read_text(encoding="utf-8")
        )["dependencies"]

        actual = {}
        for collection_name, module in (
            (
                "ansible.netcommon",
                __import__(
                    "ansible_collections.ansible.netcommon",
                    fromlist=["__path__"],
                ),
            ),
            (
                "community.routeros",
                __import__(
                    "ansible_collections.community.routeros",
                    fromlist=["__path__"],
                ),
            ),
        ):
            manifest_path = Path(next(iter(module.__path__))) / "MANIFEST.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            actual[collection_name] = manifest["collection_info"]["version"]

        self.assertEqual("2.21.2", ansible_release.__version__)
        self.assertEqual(declared, actual)


if __name__ == "__main__":
    unittest.main()

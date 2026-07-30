from __future__ import annotations

import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import install_pppoe_credentials
from install_pppoe_credentials import (
    CredentialError,
    ExpectedFingerprintPolicy,
    MAX_HISTORY_SIZE,
    SUCCESS_MARKER,
    install_credentials,
    load_pppoe_credentials,
    load_secret,
    openssh_fingerprint,
    require_interactive_terminal,
    routeros_string,
)


class RuntimeSecretTests(unittest.TestCase):
    def write_secret(
        self,
        directory: Path,
        name: str,
        contents: str,
        mode: int = 0o400,
    ) -> Path:
        secret_path = directory / name
        secret_path.write_text(contents, encoding="utf-8")
        secret_path.chmod(mode)
        return secret_path

    def test_loads_separate_runtime_secret_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            directory_path = Path(directory)
            username_path = self.write_secret(
                directory_path,
                "username",
                "synthetic-user",
            )
            password_path = self.write_secret(
                directory_path,
                "password",
                "synthetic-password",
            )
            self.assertEqual(
                load_pppoe_credentials(username_path, password_path),
                ("synthetic-user", "synthetic-password"),
            )

    def test_accepts_one_terminal_newline(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_secret(Path(directory), "secret", "synthetic\n")
            self.assertEqual(load_secret(path, "test"), "synthetic")

    def test_rejects_any_mode_other_than_0400(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            secret = "must-not-appear-in-errors"
            for index, mode in enumerate((0o600, 0o440, 0o404, 0o500)):
                path = self.write_secret(
                    Path(directory),
                    f"secret-{index}",
                    secret,
                    mode=mode,
                )
                with self.assertRaisesRegex(CredentialError, "mode 0400") as error:
                    load_secret(path, "test")
                self.assertNotIn(secret, str(error.exception))

    def test_rejects_untrusted_symlinks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            directory_path = Path(directory)
            target = self.write_secret(directory_path, "target", "synthetic")
            symlink = directory_path / "secret-link"
            symlink.symlink_to(target)
            with self.assertRaisesRegex(CredentialError, "sops-nix runtime path"):
                load_secret(symlink, "test")

    def test_accepts_sops_nix_generation_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_path = Path(directory) / "run"
            generations_path = run_path / "secrets.d"
            generation_path = generations_path / "1"
            generation_path.mkdir(parents=True)
            logical_root = run_path / "secrets"
            logical_root.symlink_to(generation_path, target_is_directory=True)
            self.write_secret(generation_path, "secret", "synthetic")

            with (
                mock.patch.object(
                    install_pppoe_credentials,
                    "SOPS_LOGICAL_ROOT",
                    logical_root,
                ),
                mock.patch.object(
                    install_pppoe_credentials,
                    "SOPS_RESOLVED_ROOT",
                    generations_path,
                ),
            ):
                self.assertEqual(
                    load_secret(logical_root / "secret", "test"),
                    "synthetic",
                )

    def test_rejects_sops_nix_path_whose_target_escapes_generations(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_path = Path(directory) / "run"
            logical_root = run_path / "secrets"
            generations_path = run_path / "secrets.d"
            logical_root.mkdir(parents=True)
            generations_path.mkdir()
            outside_path = self.write_secret(
                Path(directory),
                "outside",
                "synthetic",
            )
            (logical_root / "secret").symlink_to(outside_path)

            with (
                mock.patch.object(
                    install_pppoe_credentials,
                    "SOPS_LOGICAL_ROOT",
                    logical_root,
                ),
                mock.patch.object(
                    install_pppoe_credentials,
                    "SOPS_RESOLVED_ROOT",
                    generations_path,
                ),
                self.assertRaisesRegex(CredentialError, "sops-nix runtime path"),
            ):
                load_secret(logical_root / "secret", "test")

    def test_rejects_hard_linked_secret_target(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            directory_path = Path(directory)
            path = self.write_secret(directory_path, "secret", "synthetic")
            os.link(path, directory_path / "second-link")
            with self.assertRaisesRegex(CredentialError, "one hard link"):
                load_secret(path, "test")

    def test_rejects_outer_whitespace_and_empty_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            directory_path = Path(directory)
            for index, contents in enumerate((" synthetic", "synthetic ", "", "\n")):
                path = self.write_secret(directory_path, f"secret-{index}", contents)
                with self.assertRaises(CredentialError):
                    load_secret(path, "test")

    def test_requires_both_secret_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            directory_path = Path(directory)
            username_path = self.write_secret(
                directory_path,
                "username",
                "synthetic-user",
            )
            with self.assertRaisesRegex(CredentialError, "PPPoE password"):
                load_pppoe_credentials(
                    username_path,
                    directory_path / "missing-password",
                )


class RouterOSStringTests(unittest.TestCase):
    def test_hex_encodes_all_utf8_bytes(self) -> None:
        self.assertEqual(routeros_string('A"$;é'), r"\41\22\24\3B\C3\A9")


class FakeChannel:
    def __init__(self, status: int) -> None:
        self.status = status

    def recv_exit_status(self) -> int:
        return self.status


class FakeChannelFile(io.BytesIO):
    def __init__(self, contents: bytes, status: int) -> None:
        super().__init__(contents)
        self.channel = FakeChannel(status)


class FakeSSHClient:
    def __init__(
        self,
        responses: list[tuple[bytes, bytes, int]],
        *,
        connect_error: Exception | None = None,
    ) -> None:
        self.responses = list(responses)
        self.connect_error = connect_error
        self.policy: ExpectedFingerprintPolicy | None = None
        self.connect_arguments: dict[str, object] = {}
        self.commands: list[str] = []
        self.closed = False

    def set_missing_host_key_policy(
        self,
        policy: ExpectedFingerprintPolicy,
    ) -> None:
        self.policy = policy

    def connect(self, **arguments: object) -> None:
        self.connect_arguments = arguments
        if self.connect_error is not None:
            raise self.connect_error

    def exec_command(
        self,
        command: str,
        *,
        timeout: int,
    ) -> tuple[None, FakeChannelFile, FakeChannelFile]:
        del timeout
        self.commands.append(command)
        stdout, stderr, status = self.responses.pop(0)
        return (
            None,
            FakeChannelFile(stdout, status),
            FakeChannelFile(stderr, status),
        )

    def close(self) -> None:
        self.closed = True


class SSHInstallationTests(unittest.TestCase):
    fingerprint = "SHA256:" + ("A" * 43)

    def call_installer(
        self,
        fake_ssh: FakeSSHClient,
        *,
        pppoe_password: str = "synthetic-password",
    ) -> None:
        with mock.patch(
            "install_pppoe_credentials.paramiko.SSHClient",
            return_value=fake_ssh,
        ):
            install_credentials(
                host="192.0.2.1",
                router_username="admin",
                client_name="pppoe-test",
                expected_fingerprint=self.fingerprint,
                router_login_password="synthetic-router-login",
                pppoe_username="synthetic-user",
                pppoe_password=pppoe_password,
            )

    def test_uses_pinned_password_only_ssh_and_hex_encoded_secrets(self) -> None:
        fake_ssh = FakeSSHClient(
            [
                (f"{SUCCESS_MARKER}\r\n".encode(), b"", 0),
                (b"Flags: U - undoable, R - redoable, F - floating-undo\n", b"", 0),
                (f"{SUCCESS_MARKER}\r\n".encode(), b"", 0),
            ]
        )
        self.call_installer(fake_ssh)

        self.assertIsInstance(fake_ssh.policy, ExpectedFingerprintPolicy)
        self.assertEqual(fake_ssh.connect_arguments["hostname"], "192.0.2.1")
        self.assertFalse(fake_ssh.connect_arguments["allow_agent"])
        self.assertFalse(fake_ssh.connect_arguments["look_for_keys"])
        self.assertNotIn("synthetic-user", fake_ssh.commands[0])
        self.assertNotIn("synthetic-password", fake_ssh.commands[0])
        self.assertIn(routeros_string("synthetic-user"), fake_ssh.commands[0])
        self.assertIn(routeros_string("synthetic-password"), fake_ssh.commands[0])
        self.assertEqual(len(fake_ssh.commands), 3)
        self.assertTrue(fake_ssh.closed)

    def test_fails_before_readiness_marker_if_history_contains_password(self) -> None:
        fake_ssh = FakeSSHClient(
            [
                (f"{SUCCESS_MARKER}\r\n".encode(), b"", 0),
                (b':local infraPassword "synthetic-password"\r\n', b"", 0),
            ]
        )
        with self.assertRaisesRegex(CredentialError, "retained"):
            self.call_installer(fake_ssh)
        self.assertEqual(len(fake_ssh.commands), 2)
        self.assertTrue(fake_ssh.closed)

    def test_fails_before_readiness_marker_if_history_contains_username(self) -> None:
        fake_ssh = FakeSSHClient(
            [
                (f"{SUCCESS_MARKER}\r\n".encode(), b"", 0),
                (b':local infraUsername "synthetic-user"\r\n', b"", 0),
            ]
        )
        with self.assertRaisesRegex(CredentialError, "retained"):
            self.call_installer(fake_ssh)
        self.assertEqual(len(fake_ssh.commands), 2)
        self.assertTrue(fake_ssh.closed)

    def test_rejects_history_that_cannot_be_scanned_completely(self) -> None:
        fake_ssh = FakeSSHClient(
            [
                (f"{SUCCESS_MARKER}\r\n".encode(), b"", 0),
                (b"x" * (MAX_HISTORY_SIZE + 1), b"", 0),
            ]
        )
        with self.assertRaisesRegex(CredentialError, "unexpectedly large"):
            self.call_installer(fake_ssh)
        self.assertEqual(len(fake_ssh.commands), 2)
        self.assertTrue(fake_ssh.closed)

    def test_redacts_transport_exception_details(self) -> None:
        fake_ssh = FakeSSHClient(
            [],
            connect_error=install_pppoe_credentials.paramiko.SSHException(
                "synthetic-password"
            ),
        )
        with self.assertRaises(CredentialError) as error:
            self.call_installer(fake_ssh)
        self.assertNotIn("synthetic-password", str(error.exception))
        self.assertTrue(fake_ssh.closed)

    def test_rejects_noncanonical_fingerprint_before_connecting(self) -> None:
        fake_ssh = FakeSSHClient([])
        with mock.patch(
            "install_pppoe_credentials.paramiko.SSHClient",
            return_value=fake_ssh,
        ):
            with self.assertRaisesRegex(CredentialError, "fingerprint"):
                install_credentials(
                    host="192.0.2.1",
                    router_username="admin",
                    client_name="pppoe-test",
                    expected_fingerprint="SHA256:short",
                    router_login_password="synthetic-router-login",
                    pppoe_username="synthetic-user",
                    pppoe_password="synthetic-password",
                )
        self.assertFalse(fake_ssh.connect_arguments)


class HostKeyPolicyTests(unittest.TestCase):
    def test_accepts_only_the_expected_key_and_records_it_for_connection(self) -> None:
        key = mock.Mock()
        key.asbytes.return_value = b"synthetic-public-host-key"
        key.get_name.return_value = "ssh-ed25519"
        fingerprint = openssh_fingerprint(key)
        host_keys = mock.Mock()
        client = mock.Mock()
        client.get_host_keys.return_value = host_keys

        ExpectedFingerprintPolicy(fingerprint).missing_host_key(
            client,
            "192.0.2.1",
            key,
        )
        host_keys.add.assert_called_once_with(
            "192.0.2.1",
            "ssh-ed25519",
            key,
        )

        with self.assertRaisesRegex(
            install_pppoe_credentials.paramiko.SSHException,
            "mismatch",
        ):
            ExpectedFingerprintPolicy("SHA256:" + ("A" * 43)).missing_host_key(
                client,
                "192.0.2.1",
                key,
            )


class TerminalTests(unittest.TestCase):
    def test_rejects_noninteractive_input(self) -> None:
        with (
            mock.patch(
                "install_pppoe_credentials.sys.stdin",
                io.StringIO(),
            ),
            mock.patch(
                "install_pppoe_credentials.sys.stderr",
                io.StringIO(),
            ),
            self.assertRaisesRegex(CredentialError, "interactive terminal"),
        ):
            require_interactive_terminal()


if __name__ == "__main__":
    unittest.main()

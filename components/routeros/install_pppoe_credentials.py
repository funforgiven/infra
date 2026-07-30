#!/usr/bin/env python3

"""Install RouterOS PPPoE credentials without rendering or logging them."""

from __future__ import annotations

import argparse
import base64
import errno
import getpass
import hashlib
import hmac
import os
from pathlib import Path
import re
import stat
import sys

import paramiko


ROUTEROS_NAME = re.compile(r"[A-Za-z0-9._+-]+\Z")
SUCCESS_MARKER = "infra-pppoe-secret-installed"
MAX_SECRET_SIZE = 4_096
MAX_HISTORY_SIZE = 262_144
SOPS_LOGICAL_ROOT = Path("/run/secrets")
SOPS_RESOLVED_ROOT = Path("/run/secrets.d")
SECRET_MODE = 0o400


class CredentialError(RuntimeError):
    """A deliberately redacted credential or transport failure."""


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _resolve_secret_path(path: Path, label: str) -> Path:
    logical_path = Path(os.path.abspath(path))
    try:
        resolved_path = logical_path.resolve(strict=True)
    except OSError as error:
        raise CredentialError(f"unable to resolve the {label} secret file") from error

    if logical_path != resolved_path and not (
        _is_relative_to(logical_path, SOPS_LOGICAL_ROOT)
        and _is_relative_to(resolved_path, SOPS_RESOLVED_ROOT)
    ):
        raise CredentialError(
            f"{label} secret file must be regular or an sops-nix runtime path"
        )
    return resolved_path


def load_secret(path: Path, label: str) -> str:
    resolved_path = _resolve_secret_path(path, label)
    descriptor = -1
    open_flags = os.O_RDONLY | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        open_flags |= os.O_NOFOLLOW

    try:
        descriptor = os.open(resolved_path, open_flags)
    except OSError as error:
        if error.errno == errno.ELOOP:
            raise CredentialError(
                f"{label} secret target must be a regular non-symlink file"
            ) from error
        raise CredentialError(f"unable to open the {label} secret file") from error

    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise CredentialError(f"{label} secret target must be a regular file")
        try:
            path_metadata = os.stat(resolved_path, follow_symlinks=False)
        except OSError as error:
            raise CredentialError(
                f"unable to verify the {label} secret file"
            ) from error
        if (metadata.st_dev, metadata.st_ino) != (
            path_metadata.st_dev,
            path_metadata.st_ino,
        ):
            raise CredentialError(f"{label} secret target changed while opening it")
        if metadata.st_uid != os.getuid():
            raise CredentialError(
                f"{label} secret target must be owned by the current user"
            )
        if metadata.st_nlink != 1:
            raise CredentialError(
                f"{label} secret target must have exactly one hard link"
            )
        if stat.S_IMODE(metadata.st_mode) != SECRET_MODE:
            raise CredentialError(
                f"{label} secret target must have mode {SECRET_MODE:04o}"
            )
        if metadata.st_size > MAX_SECRET_SIZE:
            raise CredentialError(f"{label} secret file is unexpectedly large")

        try:
            with os.fdopen(descriptor, encoding="utf-8") as secret_file:
                descriptor = -1
                value = secret_file.read(MAX_SECRET_SIZE + 1)
        except (OSError, UnicodeError) as error:
            raise CredentialError(f"unable to read the {label} secret file") from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)

    if value.endswith("\n"):
        value = value[:-1]
        if value.endswith("\r"):
            value = value[:-1]
    if not value:
        raise CredentialError(f"{label} secret is empty")
    if value != value.strip():
        raise CredentialError(f"{label} secret contains unsupported outer whitespace")

    encoded_value = value.encode("utf-8")
    if len(encoded_value) > 256 or b"\x00" in encoded_value:
        raise CredentialError(f"{label} secret has an invalid encoded length")
    return value


def load_pppoe_credentials(
    username_path: Path,
    password_path: Path,
) -> tuple[str, str]:
    return (
        load_secret(username_path, "PPPoE username"),
        load_secret(password_path, "PPPoE password"),
    )


def routeros_string(value: str) -> str:
    """Encode every UTF-8 byte as a RouterOS hexadecimal string escape."""

    return "".join(f"\\{byte:02X}" for byte in value.encode("utf-8"))


def openssh_fingerprint(key: paramiko.PKey) -> str:
    digest = hashlib.sha256(key.asbytes()).digest()
    return "SHA256:" + base64.b64encode(digest).decode("ascii").rstrip("=")


class ExpectedFingerprintPolicy(paramiko.MissingHostKeyPolicy):
    def __init__(self, expected_fingerprint: str) -> None:
        self.expected_fingerprint = expected_fingerprint

    def missing_host_key(
        self,
        client: paramiko.SSHClient,
        hostname: str,
        key: paramiko.PKey,
    ) -> None:
        actual_fingerprint = openssh_fingerprint(key)
        if not hmac.compare_digest(actual_fingerprint, self.expected_fingerprint):
            raise paramiko.SSHException("RouterOS host-key fingerprint mismatch")
        client.get_host_keys().add(hostname, key.get_name(), key)


def install_credentials(
    *,
    host: str,
    router_username: str,
    client_name: str,
    expected_fingerprint: str,
    router_login_password: str,
    pppoe_username: str,
    pppoe_password: str,
) -> None:
    if not ROUTEROS_NAME.fullmatch(router_username) or not ROUTEROS_NAME.fullmatch(
        client_name
    ):
        raise CredentialError("invalid RouterOS username or PPPoE client name")
    if not re.fullmatch(r"SHA256:[A-Za-z0-9+/]{43}", expected_fingerprint):
        raise CredentialError("invalid RouterOS host-key fingerprint")

    escaped_username = routeros_string(pppoe_username)
    escaped_password = routeros_string(pppoe_password)
    command = (
        f':if ([:len [/interface pppoe-client find where name="{client_name}"]] != 1) '
        'do={ :error "infra: PPPoE client is missing or ambiguous" }; '
        f':local infraUsername "{escaped_username}"; '
        f':local infraPassword "{escaped_password}"; '
        f'/interface pppoe-client set [find where name="{client_name}"] '
        "user=$infraUsername password=$infraPassword; "
        ":set infraUsername; "
        ":set infraPassword; "
        f':put "{SUCCESS_MARKER}"'
    )
    readiness_command = ""
    history_output = ""
    marker_output = ""

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(ExpectedFingerprintPolicy(expected_fingerprint))
    try:
        ssh.connect(
            hostname=host,
            username=router_username,
            password=router_login_password,
            allow_agent=False,
            look_for_keys=False,
            timeout=8,
            banner_timeout=8,
            auth_timeout=8,
        )
        _stdin, stdout, stderr = ssh.exec_command(command, timeout=10)
        output = stdout.read(16_384).decode("utf-8", errors="replace")
        error_output = stderr.read(16_384)
        exit_status = stdout.channel.recv_exit_status()
        if (
            exit_status != 0
            or error_output
            or SUCCESS_MARKER not in output
        ):
            raise CredentialError("RouterOS rejected the PPPoE credential update")

        _history_stdin, history_stdout, history_stderr = ssh.exec_command(
            "/system history print detail without-paging",
            timeout=10,
        )
        history_bytes = history_stdout.read(MAX_HISTORY_SIZE + 1)
        if len(history_bytes) > MAX_HISTORY_SIZE:
            raise CredentialError("RouterOS credential history is unexpectedly large")
        history_output = history_bytes.decode(
            "utf-8",
            errors="replace",
        )
        history_error = history_stderr.read(16_384)
        history_status = history_stdout.channel.recv_exit_status()
        if history_status != 0 or history_error:
            raise CredentialError("unable to verify RouterOS credential history")

        doubled_username_escapes = escaped_username.replace("\\", "\\\\")
        doubled_password_escapes = escaped_password.replace("\\", "\\\\")
        sensitive_history_patterns = (
            escaped_username,
            escaped_username.lower(),
            doubled_username_escapes,
            doubled_username_escapes.lower(),
            f'infraUsername "{pppoe_username}"',
            f"infraUsername={pppoe_username}",
            f"user={pppoe_username}",
            f'user="{pppoe_username}"',
            escaped_password,
            escaped_password.lower(),
            doubled_password_escapes,
            doubled_password_escapes.lower(),
            f'infraPassword "{pppoe_password}"',
            f'infraPassword={pppoe_password}',
            f"password={pppoe_password}",
            f'password="{pppoe_password}"',
        )
        if any(
            pattern and pattern in history_output
            for pattern in sensitive_history_patterns
        ):
            raise CredentialError("RouterOS retained a PPPoE credential in history")

        readiness_command = (
            f':if ([:len [/interface pppoe-client find where name="{client_name}"]] '
            '!= 1) do={ :error "infra: PPPoE client is missing or ambiguous" }; '
            f'/interface pppoe-client set [find where name="{client_name}"] '
            'comment="infra: TurkNet PPPoE; credentials installed"; '
            f':put "{SUCCESS_MARKER}"'
        )
        _marker_stdin, marker_stdout, marker_stderr = ssh.exec_command(
            readiness_command,
            timeout=10,
        )
        marker_output = marker_stdout.read(16_384).decode(
            "utf-8",
            errors="replace",
        )
        marker_error = marker_stderr.read(16_384)
        marker_status = marker_stdout.channel.recv_exit_status()
        if (
            marker_status != 0
            or marker_error
            or SUCCESS_MARKER not in marker_output
        ):
            raise CredentialError("RouterOS rejected the credential readiness marker")
    except (OSError, EOFError, paramiko.SSHException) as error:
        raise CredentialError("secure RouterOS credential installation failed") from error
    finally:
        ssh.close()
        command = ""
        readiness_command = ""
        escaped_username = ""
        escaped_password = ""
        history_output = ""
        marker_output = ""


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Install SOPS-provisioned credentials on one RouterOS PPPoE client "
            "over host-key-pinned SSH."
        )
    )
    parser.add_argument("--host", required=True)
    parser.add_argument("--username", default="admin")
    parser.add_argument("--client", required=True)
    parser.add_argument("--fingerprint", required=True)
    parser.add_argument("--pppoe-username-file", required=True, type=Path)
    parser.add_argument("--pppoe-password-file", required=True, type=Path)
    return parser.parse_args()


def require_interactive_terminal() -> None:
    if not sys.stdin.isatty() or not sys.stderr.isatty():
        raise CredentialError("an interactive terminal is required")


def main() -> int:
    arguments = parse_arguments()
    pppoe_username = ""
    pppoe_password = ""
    router_login_password = ""
    try:
        pppoe_username, pppoe_password = load_pppoe_credentials(
            arguments.pppoe_username_file,
            arguments.pppoe_password_file,
        )
        require_interactive_terminal()
        router_login_password = getpass.getpass("RouterOS login password: ")
        if not router_login_password:
            raise CredentialError("RouterOS login password is empty")
        install_credentials(
            host=arguments.host,
            router_username=arguments.username,
            client_name=arguments.client,
            expected_fingerprint=arguments.fingerprint,
            router_login_password=router_login_password,
            pppoe_username=pppoe_username,
            pppoe_password=pppoe_password,
        )
    except CredentialError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    finally:
        pppoe_username = ""
        pppoe_password = ""
        router_login_password = ""

    print("PPPoE credentials installed securely on RouterOS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

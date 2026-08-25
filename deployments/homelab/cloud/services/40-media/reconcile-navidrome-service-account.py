#!/lsiopy/bin/python3
"""Reconcile AudioMuse's regular Navidrome account through the native CLI."""

import json
import os
import pty
import select
import signal
import subprocess
import time


NAVIDROME = os.environ.get(
    "NAVIDROME_EXECUTABLE",
    "/bootstrap-bin/navidrome",
)
USERNAME = "audiomuse"


def navidrome(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [NAVIDROME, *args],
        check=True,
        capture_output=True,
        text=True,
    )


def run_password_command(args: list[str], password: str) -> None:
    pid, master = pty.fork()
    if pid == 0:
        os.execv(NAVIDROME, [NAVIDROME, *args])

    prompts = (
        b"Enter new password",
        b"Confirm new password",
    )
    prompt_index = 0
    buffered = bytearray()
    deadline = time.monotonic() + 120
    child_status = None

    try:
        while child_status is None:
            if time.monotonic() >= deadline:
                os.kill(pid, signal.SIGTERM)
                raise TimeoutError("Navidrome user command timed out")

            readable, _, _ = select.select([master], [], [], 0.5)
            if readable:
                try:
                    buffered.extend(os.read(master, 4096))
                except OSError:
                    pass

                if (
                    prompt_index < len(prompts)
                    and prompts[prompt_index] in buffered
                ):
                    os.write(master, password.encode() + b"\n")
                    prompt_index += 1
                    buffered.clear()

            waited_pid, status = os.waitpid(pid, os.WNOHANG)
            if waited_pid == pid:
                child_status = status
    finally:
        os.close(master)

    exit_code = os.waitstatus_to_exitcode(child_status)
    if exit_code != 0:
        raise RuntimeError(f"Navidrome user command exited {exit_code}")
    if prompt_index != len(prompts):
        raise RuntimeError("Navidrome password prompts drifted")


users = json.loads(navidrome("user", "list", "--format", "json").stdout)
if not any(user["admin"] for user in users):
    raise RuntimeError("Refusing to create a service account without an admin")

password = os.environ["AUDIOMUSE_NAVIDROME_PASSWORD"]
account = next(
    (user for user in users if user["username"].casefold() == USERNAME),
    None,
)
if account is None:
    command = [
        "user",
        "create",
        "--username",
        USERNAME,
        "--name",
        "AudioMuse",
    ]
    action = "created"
else:
    command = [
        "user",
        "edit",
        "--user",
        USERNAME,
        "--set-regular",
        "--set-password",
        "--name",
        "AudioMuse",
    ]
    action = "reconciled"

run_password_command(command, password)
print(f"Navidrome service account {USERNAME!r} {action} as a regular user")

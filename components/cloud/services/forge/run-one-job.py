#!/usr/bin/env python3
"""Supervise one disposable runner without controller credentials or API access."""

import os
import re
import selectors
import signal
import subprocess
import sys
import time


UNREGISTERED = re.compile(
    rb'level=(?:warning|error) msg="Report(?:Log|State) error: '
    rb'unauthenticated: unregistered runner"(?:\s|$)'
)
TERM_GRACE_SECONDS = 20


def group_alive(group):
    try:
        os.killpg(group, 0)
    except ProcessLookupError:
        return False
    return True


def signal_group(group, signum):
    try:
        os.killpg(group, signum)
    except ProcessLookupError:
        pass


def supervise(command, output=None, grace=TERM_GRACE_SECONDS):
    """Preserve ordinary exit/output; retire a revoked runner and its children."""
    output = output if output is not None else sys.stdout.buffer
    interrupted = 0

    def interrupted_by(signum, _frame):
        nonlocal interrupted
        interrupted = signum

    handlers = {number: signal.signal(number, interrupted_by)
                for number in (signal.SIGTERM, signal.SIGINT)}
    process = None
    selector = selectors.DefaultSelector()
    revoked = False
    deadline = None
    tail = b""

    def forward(data):
        nonlocal tail, revoked
        output.write(data)
        output.flush()
        # Bound memory even if child output contains no newlines. The exact
        # runner diagnostic can be split across pipe reads.
        tail = (tail + data)[-131072:]
        if UNREGISTERED.search(tail):
            revoked = True
        tail = tail[-4096:]

    try:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   start_new_session=True, bufsize=0)
        os.set_blocking(process.stdout.fileno(), False)
        selector.register(process.stdout, selectors.EVENT_READ)
        while True:
            finished = process.poll() is not None
            if deadline is None and (interrupted or revoked or finished):
                signal_group(process.pid, signal.SIGTERM)
                deadline = time.monotonic() + grace
            if deadline is not None:
                if not group_alive(process.pid):
                    break
                if time.monotonic() >= deadline:
                    signal_group(process.pid, signal.SIGKILL)
                    break
            for key, _events in selector.select(0.05):
                data = os.read(key.fd, 65536)
                if not data:
                    selector.unregister(key.fileobj)
                    continue
                forward(data)
        process.wait(timeout=5)
        # Preserve output buffered immediately before process termination.
        while selector.get_map() and selector.select(0):
            data = os.read(process.stdout.fileno(), 65536)
            if not data:
                break
            forward(data)
        if interrupted:
            return 128 + interrupted
        if revoked:
            return 1
        return process.returncode if process.returncode >= 0 else 128 - process.returncode
    finally:
        if process is not None:
            # Also clean descendants if the runner exits before they do, or
            # forwarding output fails. No child can retain the disposable slot.
            signal_group(process.pid, signal.SIGKILL)
            process.wait(timeout=5)
            process.stdout.close()
        selector.close()
        for number, handler in handlers.items():
            signal.signal(number, handler)


def main():
    command = sys.argv[1:]
    if command[:1] == ["--"]:
        command = command[1:]
    if not command:
        print("run-one-job: a runner command is required", file=sys.stderr)
        return 2
    return supervise(command)


if __name__ == "__main__":
    raise SystemExit(main())

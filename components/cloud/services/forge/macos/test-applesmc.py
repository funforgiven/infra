#!/usr/bin/env python3
"""Exercise the built QEMU AppleSMC device through its real qtest I/O ports.

Usage: python3 test-applesmc.py /path/to/qemu-system-x86_64
No firmware or guest code is executed; no KVM, network or real OSK is used.
"""

import os
from pathlib import Path
import selectors
import subprocess
import sys
import tempfile
import time
import unittest


BINARY = str(Path(sys.argv.pop(1)).resolve())
DATA, STATUS, RESULT = 0x300, 0x304, 0x31E
READ, INDEX = 0x10, 0x12
DONE, ACK, READY, NEW = 0, 4, 5, 12
PUBLIC = (b"MSSD", b"MSSP", b"NATJ", b"REV ")
# Deliberately synthetic and different halves, so stale OSK data is detectable.
DUMMY_OSK = "A" * 32 + "B" * 32
SUITE_DEADLINE = time.monotonic() + 120


class SMC:
    def __init__(self):
        self.stderr = tempfile.TemporaryFile()
        self.process = subprocess.Popen(
            [BINARY, "-machine", "q35", "-accel", "qtest", "-display", "none",
             "-nodefaults", "-S", "-qtest", "stdio", "-qtest-log", "none",
             "-device", f"isa-applesmc,osk={DUMMY_OSK}"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.stderr,
            bufsize=0,
        )
        self.selector = selectors.DefaultSelector()
        self.selector.register(self.process.stdout, selectors.EVENT_READ)

    def close(self):
        self.selector.close()
        if self.process.poll() is None:
            self.process.terminate()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)
        self.process.stdin.close()
        self.process.stdout.close()
        self.stderr.close()

    def command(self, command):
        deadline = min(time.monotonic() + 10, SUITE_DEADLINE)
        self.process.stdin.write(command.encode("ascii") + b"\n")
        line = bytearray()
        while not line.endswith(b"\n"):
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not self.selector.select(timeout=remaining):
                raise AssertionError(f"qtest response timed out: {command}")
            chunk = os.read(self.process.stdout.fileno(), 1)
            if not chunk:
                self.stderr.seek(0)
                detail = self.stderr.read(4096).decode("utf-8", errors="replace")
                raise AssertionError(f"QEMU exited during {command}: {detail}")
            line += chunk
            if len(line) > 1024:
                raise AssertionError("oversized qtest response")
        fields = line.decode("ascii").split()
        if not fields or fields[0] != "OK":
            raise AssertionError(f"qtest rejected {command}: {line!r}")
        return fields[1:]

    def outb(self, port, value):
        result = self.command(f"outb {port:#x} {value:#x}")
        if result:
            raise AssertionError(f"unexpected outb response: {result}")

    def inb(self, port):
        result = self.command(f"inb {port:#x}")
        if len(result) != 1:
            raise AssertionError(f"unexpected inb response: {result}")
        return int(result[0], 0)


class AppleSMCTest(unittest.TestCase):
    def setUp(self):
        self.smc = SMC()
        self.addCleanup(self.smc.close)
        self.assertEqual(self.smc.inb(STATUS), DONE)
        self.assertEqual(self.smc.inb(RESULT), 0)

    def start(self, command):
        self.smc.outb(STATUS, command)
        self.assertEqual(
            self.smc.inb(STATUS), NEW,
            f"command {command:#x}, result {self.smc.inb(RESULT):#x}",
        )

    def request_index(self, index, legacy_length=False):
        self.start(INDEX)
        for position, value in enumerate(index.to_bytes(4, "big")):
            self.smc.outb(DATA, value)
            self.assertEqual(self.smc.inb(STATUS), READY if position == 3 else ACK)
        if legacy_length:
            self.smc.outb(DATA, 4)
            self.assertEqual(self.smc.inb(STATUS), READY)

    def reply(self, size, result=0):
        self.assertEqual(self.smc.inb(RESULT), result)
        value = bytearray()
        for position in range(size):
            self.assertEqual(self.smc.inb(STATUS), READY)
            value.append(self.smc.inb(DATA))
            self.assertEqual(self.smc.inb(STATUS), DONE if position == size - 1 else READY)
            self.assertEqual(self.smc.inb(RESULT), result)
        # The result port must be persistent rather than clear-on-read.
        self.assertEqual(self.smc.inb(RESULT), result)
        return bytes(value)

    def read_key(self, key, size):
        self.start(READ)
        for value in key:
            self.smc.outb(DATA, value)
            self.assertEqual(self.smc.inb(STATUS), ACK)
        self.smc.outb(DATA, size)

    def test_public_enumeration_finishes_at_exact_range_error(self):
        observed = []
        for index in range(len(PUBLIC)):
            self.request_index(index)
            observed.append(self.reply(4))
        self.assertEqual(tuple(observed), PUBLIC)
        self.assertEqual(observed, sorted(set(observed)))
        self.assertNotIn(b"OSK0", observed)
        self.assertNotIn(b"OSK1", observed)
        self.request_index(len(PUBLIC))
        self.assertEqual(self.reply(4, 0xB8), bytes(4))

    def test_big_endian_range_boundaries_do_not_wrap(self):
        for index in (4, 5, 6, 255, 256, 65536, 0x80000000, 0xFFFFFFFF):
            with self.subTest(index=index):
                self.request_index(index)
                self.assertEqual(self.reply(4, 0xB8), bytes(4))
                self.assertEqual(self.smc.inb(DATA), 0)
                self.assertEqual(self.smc.inb(RESULT), 0xB8)

    def test_legacy_optional_length_byte(self):
        for index in (0, 3, 4):
            self.request_index(index, legacy_length=True)
            if index < len(PUBLIC):
                self.assertEqual(self.reply(4), PUBLIC[index])
            else:
                self.assertEqual(self.reply(4, 0xB8), bytes(4))

    def test_named_osk_reads_remain_supported_and_range_reply_has_no_stale_data(self):
        for key, expected in ((b"OSK0", b"A" * 32), (b"OSK1", b"B" * 32)):
            self.read_key(key, 32)
            self.assertEqual(self.reply(32), expected)
            self.request_index(0xFFFFFFFF)
            self.assertEqual(self.reply(4, 0xB8), bytes(4))
            self.assertEqual(self.smc.inb(DATA), 0)

    def test_unknown_read_retains_noexist_and_valid_operations_clear_errors(self):
        self.read_key(b"NONE", 4)
        self.assertEqual(self.smc.inb(STATUS), DONE)
        self.assertEqual(self.smc.inb(RESULT), 0x84)
        self.request_index(0)
        self.assertEqual(self.reply(4), PUBLIC[0])
        self.request_index(4)
        self.assertEqual(self.reply(4, 0xB8), bytes(4))
        self.read_key(b"REV ", 6)
        self.assertEqual(self.reply(6), b"\x01\x13\x0f\x00\x00\x03")

    def test_index_waits_for_four_bytes_and_ignores_extra_writes_without_wrap(self):
        self.read_key(b"OSK1", 32)
        self.assertEqual(self.reply(32), b"B" * 32)
        self.start(INDEX)
        for value in (0, 0, 0):
            self.smc.outb(DATA, value)
            self.assertEqual(self.smc.inb(STATUS), ACK)
            self.assertEqual(self.smc.inb(DATA), 0)
            self.assertEqual(self.smc.inb(STATUS), ACK)
        self.smc.outb(DATA, 2)
        self.assertEqual(self.smc.inb(STATUS), READY)
        for _ in range(260):
            self.smc.outb(DATA, 0xFF)
        self.assertEqual(self.reply(4), b"NATJ")

    def test_interrupted_index_requires_new_accepted_command(self):
        self.start(INDEX)
        self.smc.outb(DATA, 0)
        self.smc.outb(STATUS, READ)
        self.assertEqual(self.smc.inb(STATUS), 8)
        self.assertEqual(self.smc.inb(RESULT), 0x80)
        self.smc.outb(DATA, 0)
        self.assertEqual(self.smc.inb(STATUS), DONE)
        self.assertEqual(self.smc.inb(RESULT), 0x81)
        self.request_index(1)
        self.assertEqual(self.reply(4), b"MSSP")

    def test_undrained_range_error_collides_once_then_recovers(self):
        for command in (READ, INDEX):
            for consumed in (0, 1, 3):
                with self.subTest(command=command, consumed=consumed):
                    self.request_index(4)
                    self.assertEqual(self.smc.inb(RESULT), 0xB8)
                    for _ in range(consumed):
                        self.assertEqual(self.smc.inb(DATA), 0)
                    self.assertEqual(self.smc.inb(STATUS), READY)
                    self.smc.outb(STATUS, command)
                    self.assertEqual(self.smc.inb(STATUS), 8)
                    self.assertEqual(self.smc.inb(RESULT), 0x80)
                    if command == READ:
                        self.read_key(b"NATJ", 1)
                        self.assertEqual(self.reply(1), b"\0")
                    else:
                        self.request_index(0)
                        self.assertEqual(self.reply(4), PUBLIC[0])

    def test_bad_command_cannot_continue_previous_read_or_index(self):
        for previous in (READ, INDEX):
            self.start(previous)
            self.smc.outb(DATA, 0)
            self.smc.outb(STATUS, 0x7F)
            self.assertEqual(self.smc.inb(STATUS), 8)
            self.assertEqual(self.smc.inb(RESULT), 0x82)
            self.smc.outb(DATA, 0)
            self.assertEqual(self.smc.inb(STATUS), DONE)
            self.assertEqual(self.smc.inb(RESULT), 0x81)
            self.request_index(3)
            self.assertEqual(self.reply(4), b"REV ")


if __name__ == "__main__":
    unittest.main(verbosity=2)

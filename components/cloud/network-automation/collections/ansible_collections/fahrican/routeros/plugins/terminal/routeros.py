# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt)

from __future__ import annotations

import re

from ansible.errors import AnsibleConnectionFailure
from ansible_collections.community.routeros.plugins.terminal.routeros import (
    TerminalModule as CommunityRouterOSTerminalModule,
)


class TerminalModule(CommunityRouterOSTerminalModule):
    """Answer RouterOS control queries during initial shell negotiation."""

    # community.routeros strips every ECMA-48 CSI before network_cli checks
    # initial prompts. Preserve only Device Status Report 6 (cursor position)
    # so the initial-login handler below can answer it; retain the other
    # upstream stripping behavior byte for byte.
    ansi_re = [
        re.compile(br"(\x1b\[\?1h\x1b=)"),
        re.compile(
            br"((?:\x9b|\x1b\x5b)(?!6n)"
            br"[\x30-\x3f]*[\x20-\x2f]*[\x40-\x7e])"
        ),
        re.compile(br"\x08."),
    ]

    terminal_initial_prompt = [br"\x1bZ", br"\x1b\[6n"]
    terminal_initial_answer = [b"\x1b/Z", b"\x1b[1;1R"]
    terminal_inital_prompt_newline = False

    _query_re = re.compile(br"\x1bZ|\x1b\[6n")
    _query_answers = {
        b"\x1bZ": b"\x1b/Z",
        b"\x1b[6n": b"\x1b[1;1R",
    }
    _query_prefixes = (b"\x1b", b"\x1b[", b"\x1b[6")

    def __init__(self, connection):
        super().__init__(connection)
        self._upstream_strip = connection._strip
        self._query_tail = b""
        connection._strip = self._strip_and_answer_queries

    def _strip_and_answer_queries(self, data):
        """Answer RouterOS terminal queries in every receive path.

        network_cli invokes _handle_prompt only when a module supplied an
        interactive prompt list. RouterOS may issue Device Attributes or
        cursor-position queries while an ordinary command is running, so the
        read-path hook is the only place shared by login and command receives.
        A short tail preserves a query split across libssh receive windows.
        """

        combined = self._query_tail + data
        visible = bytearray()
        offset = 0
        for match in self._query_re.finditer(combined):
            visible.extend(combined[offset : match.start()])
            query = match.group(0)
            if self._connection._ssh_shell is None:
                raise AnsibleConnectionFailure(
                    "RouterOS terminal query arrived before the SSH shell opened"
                )
            self._connection._ssh_shell.sendall(self._query_answers[query])
            offset = match.end()
        visible.extend(combined[offset:])

        stripped_queries = bytes(visible)
        tail_length = max(
            (
                len(prefix)
                for prefix in self._query_prefixes
                if stripped_queries.endswith(prefix)
            ),
            default=0,
        )
        if tail_length:
            self._query_tail = stripped_queries[-tail_length:]
            stripped_queries = stripped_queries[:-tail_length]
        else:
            self._query_tail = b""

        return self._upstream_strip(stripped_queries)

    def on_open_shell(self):
        return super().on_open_shell()

    def on_close_shell(self):
        try:
            return super().on_close_shell()
        finally:
            self._connection._strip = self._upstream_strip

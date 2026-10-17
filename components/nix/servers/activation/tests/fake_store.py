"""In-memory stand-in for SopsCredentialStore."""

from __future__ import annotations

from pathlib import Path

from sops_credentials import SopsCredentialError


class FakeStore:
    def __init__(
        self,
        *,
        events: list[str] | None = None,
        fail_writes: bool = False,
    ) -> None:
        self.values: dict[tuple[Path, str], str] = {}
        self.writes: list[tuple[Path, dict[str, str]]] = []
        self.events = events
        self.fail_writes = fail_writes

    def read(self, secret_file: Path, credential: str) -> str | None:
        return self.values.get((secret_file, credential))

    def write(self, secret_file: Path, values: dict[str, str]) -> None:
        if self.events is not None:
            self.events.append("sops:write-and-verify")
        if self.fail_writes:
            raise SopsCredentialError("simulated SOPS write failure")
        self.values.update(
            {(secret_file, credential): value for credential, value in values.items()}
        )
        self.writes.append((secret_file, dict(values)))

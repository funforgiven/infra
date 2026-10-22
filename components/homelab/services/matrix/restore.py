#!/usr/bin/env python3
"""Offline verifier for restored Matrix media and relay recovery snapshots.

PostgreSQL is verified separately by the CloudNativePG restore test.
"""

import json
import os
import shutil
import sqlite3
from pathlib import Path


def main():
    work = Path(os.environ.get("MATRIX_RESTORE_WORK", "/tmp"))
    media = Path(os.environ.get("MATRIX_RESTORE_MEDIA", "/var/lib/matrix/media"))
    if not media.is_dir():
        raise ValueError("media volume absent")
    relay = Path(
        os.environ.get("MATRIX_RESTORE_RELAY", "/var/lib/matrix/relay/backups")
    )
    databases = list(relay.glob("*.db")) + list(relay.glob("*.sqlite"))
    if not databases:
        raise ValueError("relay recovery snapshots absent")
    # A standalone SQLite backup can retain WAL journal mode, and SQLite may need
    # WAL/SHM files even for a read-only connection. Keep the recovered claim
    # read-only and inspect writable copies.
    state = work / "restored-relay"
    state.mkdir()
    for backup in databases:
        restored = state / backup.name
        shutil.copyfile(backup, restored)
        for suffix in ("-wal", "-shm"):
            sidecar = backup.with_name(backup.name + suffix)
            if sidecar.is_file():
                shutil.copyfile(sidecar, restored.with_name(restored.name + suffix))
        with sqlite3.connect(f"file:{restored}?mode=ro", uri=True) as connection:
            if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("relay snapshot corrupt")
    from nio import AsyncClient, AsyncClientConfig

    identity = json.loads((relay / "identity.json").read_text())
    client = AsyncClient(
        "http://127.0.0.1",
        identity["user_id"],
        device_id=identity["device_id"],
        store_path=str(state),
        config=AsyncClientConfig(encryption_enabled=True, store_sync_tokens=True),
    )
    client.restore_login(
        identity["user_id"], identity["device_id"], "offline-verification"
    )
    if client.olm.account.identity_keys["ed25519"] != identity["ed25519"]:
        raise ValueError("restored bot crypto identity changed")
    canary = identity["canary"]
    incoming = client.olm.inbound_group_store.get(
        canary["room_id"], canary["sender_key"], canary["session_id"]
    )
    if (
        incoming is None
        or incoming.decrypt(canary["ciphertext"])[0]
        != "Matrix crypto recovery qualification"
    ):
        raise ValueError("restored crypto session failed to decrypt recovery canary")
    print("Matrix media volume, relay queue, bot identity and recovery canary verified.")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        raise SystemExit(
            "Isolated Matrix restore verification failed; diagnostics suppressed."
        ) from None

#!/usr/bin/env python3
"""Offline dump verifier and isolated restore of both Matrix databases."""

import hashlib
import json
import os
import subprocess
from pathlib import Path


def main():
    directory = Path(os.environ.get("MATRIX_RESTORE_DUMPS", "/var/lib/matrix/dumps"))
    latest = sorted(directory.glob("complete-*"), reverse=True)[0]
    manifest = json.loads((latest / "manifest.json").read_text())
    work = Path(os.environ.get("MATRIX_RESTORE_WORK", "/tmp"))
    data = work / "restore-postgres"

    def run(argv, stdin=None):
        return subprocess.run(argv, input=stdin, capture_output=True, check=True).stdout

    run(
        [
            "initdb",
            "-D",
            str(data),
            "--username",
            "postgres",
            "--auth",
            "trust",
            "--locale",
            "C",
            "--encoding",
            "UTF8",
        ]
    )
    run(
        [
            "pg_ctl",
            "-D",
            str(data),
            "-w",
            "start",
            "-l",
            str(work / "restore.log"),
            "-o",
            f"-k {work} -h ''",
        ]
    )
    try:
        for database in ("synapse", "mas"):
            dump = latest / (database + ".dump")
            with dump.open("rb") as file:
                if (
                    hashlib.file_digest(file, "sha256").hexdigest()
                    != manifest[dump.name]
                ):
                    raise ValueError("dump checksum mismatch")
            run(["createdb", "-h", str(work), "-U", "postgres", database])
            run(
                [
                    "pg_restore",
                    "-h",
                    str(work),
                    "-U",
                    "postgres",
                    "--no-owner",
                    "--no-acl",
                    "--exit-on-error",
                    "-d",
                    database,
                    str(dump),
                ]
            )
            count = run(
                [
                    "psql",
                    "-h",
                    str(work),
                    "-U",
                    "postgres",
                    "-d",
                    database,
                    "-Atc",
                    "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'",
                ]
            )
            if int(count) < 1:
                raise ValueError("restored database is empty")
        media = Path(os.environ.get("MATRIX_RESTORE_MEDIA", "/var/lib/matrix/media"))
        if not media.is_dir():
            raise ValueError("media volume absent")
        relay = Path(
            os.environ.get("MATRIX_RESTORE_RELAY", "/var/lib/matrix/relay/backups")
        )
        import sqlite3

        databases = list(relay.glob("*.db")) + list(relay.glob("*.sqlite"))
        if not databases:
            raise ValueError("relay recovery snapshots absent")
        for backup in databases:
            with sqlite3.connect(f"file:{backup}?mode=ro", uri=True) as connection:
                if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise ValueError("relay snapshot corrupt")
        # Open an isolated copy of the backed-up crypto store, never a live store.
        import shutil
        from nio import AsyncClient, AsyncClientConfig

        identity = json.loads((relay / "identity.json").read_text())
        state = work / "restored-crypto"
        state.mkdir()
        for backup in relay.glob("*.db"):
            shutil.copyfile(backup, state / backup.name)
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
            raise ValueError(
                "restored crypto session failed to decrypt recovery canary"
            )
        print(
            "Both Matrix databases restored; media volume, queue, bot identity and recovered decryption session verified."
        )
    finally:
        run(["pg_ctl", "-D", str(data), "-w", "stop", "-m", "fast"])


if __name__ == "__main__":
    try:
        main()
    except Exception:
        raise SystemExit(
            "Isolated Matrix restore qualification failed; diagnostics suppressed."
        ) from None

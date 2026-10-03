#!/usr/bin/env python3
"""Initialize dedicated Matrix databases; credentials cross subprocess stdin only."""

import os
import re
import subprocess
from pathlib import Path

DATA = Path("/var/lib/matrix/postgres/pgdata")


def command(argv, data=None):
    result = subprocess.run(argv, input=data, capture_output=True)
    if result.returncode:
        raise RuntimeError("PostgreSQL initialization failed; diagnostics suppressed")
    return result.stdout


def main():
    if not (DATA / "PG_VERSION").exists():
        command(
            [
                "initdb",
                "-D",
                str(DATA),
                "--username",
                "postgres",
                "--pwfile",
                "/run/matrix/postgres-password",
                "--auth-host",
                "scram-sha-256",
                "--auth-local",
                "trust",
                "--encoding",
                "UTF8",
                "--locale",
                "C",
            ]
        )
    command(
        [
            "pg_ctl",
            "-D",
            str(DATA),
            "-w",
            "start",
            "-l",
            "/tmp/postgres-init.log",
            "-o",
            "-k /tmp -h 127.0.0.1",
        ]
    )
    try:
        for name in ("synapse", "mas"):
            password = Path("/run/matrix/" + name + "-password").read_text()
            if not re.fullmatch(r"[a-f0-9]{64}", password):
                raise ValueError("invalid database credential")
            roles = (
                command(
                    [
                        "psql",
                        "-h",
                        "/tmp",
                        "-U",
                        "postgres",
                        "-Atc",
                        "SELECT rolname FROM pg_roles",
                    ]
                )
                .decode()
                .splitlines()
            )
            operation = "ALTER" if name in roles else "CREATE"
            sql = f"{operation} ROLE {name} WITH LOGIN PASSWORD '{password}';\n"
            command(
                ["psql", "-h", "/tmp", "-U", "postgres", "-v", "ON_ERROR_STOP=1"],
                sql.encode(),
            )
            databases = (
                command(
                    [
                        "psql",
                        "-h",
                        "/tmp",
                        "-U",
                        "postgres",
                        "-Atc",
                        "SELECT datname FROM pg_database",
                    ]
                )
                .decode()
                .splitlines()
            )
            if name not in databases:
                sql = f"CREATE DATABASE {name} OWNER {name} ENCODING 'UTF8' LC_COLLATE 'C' LC_CTYPE 'C' TEMPLATE template0;\n"
                command(
                    ["psql", "-h", "/tmp", "-U", "postgres", "-v", "ON_ERROR_STOP=1"],
                    sql.encode(),
                )
    finally:
        command(["pg_ctl", "-D", str(DATA), "-w", "stop", "-m", "fast"])
    os.execvp("postgres", ["postgres", "-D", str(DATA), "-h", "0.0.0.0", "-k", "/tmp"])


if __name__ == "__main__":
    try:
        main()
    except Exception:
        raise SystemExit(
            "PostgreSQL initialization failed; diagnostics suppressed."
        ) from None

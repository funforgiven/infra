#!/usr/bin/env python3
"""Initialize dedicated Matrix databases; credentials cross subprocess stdin only."""

import os
import re
import subprocess
from pathlib import Path

DATA = Path(os.environ.get("MATRIX_POSTGRES_DATA", "/var/lib/matrix/postgres/pgdata"))
CREDENTIALS = Path(os.environ.get("MATRIX_SECRET_DIR", "/run/matrix"))
SOCKET = os.environ.get("MATRIX_POSTGRES_SOCKET", "/tmp")
PORT = os.environ.get("MATRIX_DB_PORT", "5432")


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
                str(CREDENTIALS / "postgres-password"),
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
    # initdb permits only loopback TCP by default. Admit the two application
    # roles from the services pod range with password authentication; PostgreSQL
    # administration remains on the local socket.
    hba = DATA / "pg_hba.conf"
    content = hba.read_text()
    for name in ("synapse", "mas"):
        entry = f"host {name} {name} 172.16.0.0/12 scram-sha-256"
        if entry not in content.splitlines():
            content += "\n" + entry + "\n"
    hba.write_text(content)
    command(
        [
            "pg_ctl",
            "-D",
            str(DATA),
            "-w",
            "start",
            "-l",
            str(Path(SOCKET) / "postgres-init.log"),
            "-o",
            f"-k {SOCKET} -h 127.0.0.1 -p {PORT}",
        ]
    )
    try:
        for name in ("synapse", "mas"):
            password = (CREDENTIALS / (name + "-password")).read_text()
            if not re.fullmatch(r"[a-f0-9]{64}", password):
                raise ValueError("invalid database credential")
            roles = (
                command(
                    [
                        "psql",
                        "-h",
                        SOCKET,
                        "-p",
                        PORT,
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
                [
                    "psql",
                    "-h",
                    SOCKET,
                    "-p",
                    PORT,
                    "-U",
                    "postgres",
                    "-v",
                    "ON_ERROR_STOP=1",
                ],
                sql.encode(),
            )
            databases = (
                command(
                    [
                        "psql",
                        "-h",
                        SOCKET,
                        "-p",
                        PORT,
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
                    [
                        "psql",
                        "-h",
                        SOCKET,
                        "-p",
                        PORT,
                        "-U",
                        "postgres",
                        "-v",
                        "ON_ERROR_STOP=1",
                    ],
                    sql.encode(),
                )
    finally:
        command(["pg_ctl", "-D", str(DATA), "-w", "stop", "-m", "fast"])
    os.execvp(
        "postgres",
        ["postgres", "-D", str(DATA), "-h", "0.0.0.0", "-p", PORT, "-k", SOCKET],
    )


if __name__ == "__main__":
    try:
        main()
    except Exception:
        raise SystemExit(
            "PostgreSQL initialization failed; diagnostics suppressed."
        ) from None

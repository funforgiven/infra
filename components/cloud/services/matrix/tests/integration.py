#!/usr/bin/env python3
"""Disposable loopback Synapse/MAS/PostgreSQL and real encrypted-client qualification.

Run with matrix-python and the Nix runtime tools on PATH. No live credentials or
homelab services are used. The process needs permission to bind loopback ports.
"""

import asyncio
import base64
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
import urllib.error
from pathlib import Path

import yaml
from aiohttp import ClientSession, web
from nio import (
    AsyncClient,
    AsyncClientConfig,
    RoomCreateResponse,
    RoomMessageText,
    RoomPreset,
    RoomSendResponse,
    SyncResponse,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from relay import Queue, check_room, snapshot_crypto


async def qualify_relay(directory, bot, owner, token, room, decrypted, proxy_port):
    canary = await bot.room_create(
        name="Relay-only canary",
        preset=RoomPreset.private_chat,
        initial_state=[
            {
                "type": "m.room.encryption",
                "state_key": "",
                "content": {"algorithm": "m.megolm.v1.aes-sha2"},
            }
        ],
    )
    assert isinstance(canary, RoomCreateResponse)
    heartbeat_port, intake_port, backup_port = [port() for _ in range(3)]
    heartbeat_seen = asyncio.Event()

    async def heartbeat(request):
        if request.headers.get("Authorization") != "Bearer synthetic-heartbeat":
            raise web.HTTPUnauthorized()
        heartbeat_seen.set()
        return web.Response(status=202)

    application = web.Application()
    application.router.add_post("/heartbeat", heartbeat)
    runner = web.AppRunner(application, access_log=None)
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", heartbeat_port).start()
    configuration = {
        "homeserver": f"http://127.0.0.1:{proxy_port}",
        "user_id": bot.user_id,
        "device_id": bot.device_id,
        "access_token": token,
        "room_id": room,
        "canary_room_id": canary.room_id,
        "allowed_users": [bot.user_id, owner.user_id],
        "trusted_devices": {
            owner.user_id: {owner.device_id: owner.olm.account.identity_keys["ed25519"]}
        },
        "producers": {"test": {"paths": ["/notify"], "token": "synthetic-intake"}},
        "heartbeat": {
            "url": f"http://127.0.0.1:{heartbeat_port}/heartbeat",
            "token": "synthetic-heartbeat",
        },
    }
    config_file = directory / "relay.json"
    config_file.write_text(json.dumps(configuration))
    await bot.close()
    environment = dict(
        os.environ,
        RELAY_PORT=str(intake_port),
        RELAY_BACKUP_PORT=str(backup_port),
        RELAY_CONFIG=str(config_file),
        RELAY_STATE=str(directory / "infra-alerts"),
    )
    process = subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve().parents[1] / "relay.py")],
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        async with ClientSession() as session:
            for _ in range(100):
                try:
                    async with session.get(
                        f"http://127.0.0.1:{intake_port}/health"
                    ) as response:
                        if response.status == 200:
                            break
                except OSError:
                    pass
                await asyncio.sleep(0.1)
            else:
                raise RuntimeError("production relay did not start")
            payload = {
                "producer_id": "test",
                "event_id": "relay-qualification",
                "host": "test",
                "unit": "qualification.service",
                "severity": "critical",
                "message": "HTTP relay encrypted qualification",
            }
            headers = {"Authorization": "Bearer synthetic-intake"}
            async with session.post(
                f"http://127.0.0.1:{intake_port}/alertmanager", json={}, headers=headers
            ) as response:
                assert response.status == 401
            for _ in range(2):
                async with session.post(
                    f"http://127.0.0.1:{intake_port}/notify",
                    json=payload,
                    headers=headers,
                ) as response:
                    assert response.status == 202
            for _ in range(30):
                await owner.sync(timeout=500)
                if any(
                    "HTTP relay encrypted qualification" in message
                    for message in decrypted
                ):
                    break
                await asyncio.sleep(0.1)
            assert (
                sum(
                    "HTTP relay encrypted qualification" in message
                    for message in decrypted
                )
                == 1
            )
            await asyncio.wait_for(heartbeat_seen.wait(), timeout=15)
            async with session.post(
                f"http://127.0.0.1:{backup_port}/snapshot"
            ) as response:
                assert response.status == 200
            print(
                "PASS: production relay HTTP intake, scoped authentication, deduplication, recipient decryption, encrypted heartbeat and snapshot"
            )
    finally:
        process.terminate()
        try:
            process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()
        await runner.cleanup()


def port():
    with socket.socket() as connection:
        connection.bind(("127.0.0.1", 0))
        return connection.getsockname()[1]


def run(argv, data=None):
    return subprocess.run(argv, input=data, capture_output=True, check=True).stdout


def http(url, host=None):
    try:
        request = urllib.request.Request(url, headers={"Host": host} if host else {})
        with urllib.request.urlopen(request, timeout=2) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, b""


async def qualify(directory, pg_port, synapse_port, mas_port, proxy_port):
    clients = []
    user_tokens = {}
    for username in ("infra-alerts", "owner"):
        run(
            [
                "mas-cli",
                "manage",
                "register-user",
                "--yes",
                "--no-admin",
                username,
                "--config",
                str(directory / "mas.yaml"),
            ]
        )
        for attempt in range(30):
            result = subprocess.run(
                [
                    "mas-cli",
                    "manage",
                    "issue-compatibility-token",
                    username,
                    username.upper(),
                    "--config",
                    str(directory / "mas.yaml"),
                ],
                capture_output=True,
            )
            if not result.returncode:
                token = (result.stdout + result.stderr).decode()
                break
            await asyncio.sleep(0.2)
        else:
            diagnostic = re.sub(
                r"mct_[A-Za-z0-9_-]+",
                "[synthetic token]",
                result.stderr.decode()[-1800:],
            )
            raise RuntimeError("Synthetic MAS token enrollment failed: " + diagnostic)
        match = re.search(r"mct_[A-Za-z0-9_-]+", token)
        if not match:
            template = re.sub(r"[A-Za-z0-9_-]{20,}", "[redacted]", token)
            raise RuntimeError(
                "MAS compatibility token format changed: " + template[-1500:]
            )
        user_tokens[username] = match.group()
        state = directory / username
        state.mkdir()
        client = AsyncClient(
            f"http://127.0.0.1:{proxy_port}",
            f"@{username}:matrix.fahrican.com",
            device_id=username.upper(),
            store_path=str(state),
            config=AsyncClientConfig(encryption_enabled=True, store_sync_tokens=True),
        )
        client.restore_login(
            f"@{username}:matrix.fahrican.com", username.upper(), match.group()
        )
        clients.append(client)
    bot, owner = clients
    try:
        for client in clients:
            response = await client.sync(full_state=True)
            if not isinstance(response, SyncResponse):
                raise RuntimeError("MAS compatibility session rejected by Synapse")
            await client.keys_upload()
        created = await bot.room_create(
            name="Disposable encrypted qualification",
            alias="qualification",
            invite=[owner.user_id],
            preset=RoomPreset.private_chat,
            initial_state=[
                {
                    "type": "m.room.encryption",
                    "state_key": "",
                    "content": {"algorithm": "m.megolm.v1.aes-sha2"},
                }
            ],
        )
        if not isinstance(created, RoomCreateResponse):
            raise RuntimeError("encrypted room creation failed")
        room = created.room_id
        joined_local = await owner.join("#qualification:matrix.fahrican.com")
        if joined_local.__class__.__name__ != "JoinResponse":
            raise RuntimeError(
                "escaped local room alias did not survive reverse proxying"
            )
        for client in clients:
            await client.sync(full_state=True)
            await client.joined_members(room)
            await client.keys_query()
        for client in clients:
            for user in client.rooms[room].users:
                for device in client.device_store.active_user_devices(user):
                    client.verify_device(device)
        try:
            check_room(bot, room, [bot.user_id, owner.user_id], {})
        except ValueError:
            pass
        else:
            raise RuntimeError("relay accepted an unapproved recipient device")
        check_room(
            bot,
            room,
            [bot.user_id, owner.user_id],
            {
                owner.user_id: {
                    owner.device_id: owner.olm.account.identity_keys["ed25519"]
                }
            },
        )
        sent = await bot.room_send(
            room,
            "m.room.message",
            {"msgtype": "m.text", "body": "Encrypted qualification canary"},
            tx_id="qualification",
        )
        if not isinstance(sent, RoomSendResponse):
            raise RuntimeError("encrypted send failed")
        decrypted = []
        owner.add_event_callback(
            lambda _room, event: decrypted.append(event.body), RoomMessageText
        )
        for attempt in range(10):
            await owner.sync(timeout=100)
            if "Encrypted qualification canary" in decrypted:
                break
            await asyncio.sleep(0.1)
        if "Encrypted qualification canary" not in decrypted:
            raise RuntimeError("recipient could not decrypt the canary")
        # Confirm encryption on the server independently of the client decrypt path.
        request = urllib.request.Request(
            f"http://127.0.0.1:{proxy_port}/_matrix/client/v3/rooms/{room}/event/{sent.event_id}",
            headers={"Authorization": "Bearer " + user_tokens["infra-alerts"]},
        )
        with urllib.request.urlopen(request) as response:
            stored = json.load(response)
        if stored["type"] != "m.room.encrypted" or "body" in stored["content"]:
            raise RuntimeError("server received plaintext")
        for path in (
            "/_matrix/federation/v1/version",
            "/_synapse/admin/v1/server_version",
            "/_matrix/key/v2/server",
        ):
            assert http(f"http://127.0.0.1:{proxy_port}" + path)[0] == 404, path
        for path in (
            "/_matrix/media/v3/download/matrix.org/test",
            "/_matrix/client/v1/media/download/matrix.org/test",
            "/_matrix/client/v1/media/download/matrix%2eorg/test",
            "/_matrix/client/v1/media/download/matrix.fahrican.com/../../download/matrix.org/test",
        ):
            assert http(f"http://127.0.0.1:{proxy_port}" + path)[0] in (403, 404), path
        for path in (
            "/ui/console/",
            "/admin/v1/",
            "/management/v1/",
            "/system/v1/",
            "/v2/users",
        ):
            assert (
                http(
                    f"http://127.0.0.1:{proxy_port}" + path, "auth.cloud.fahrican.com"
                )[0]
                == 404
            ), path
        # An outbound room join must fail with federation denied.
        joined = await bot.join("#matrix:matrix.org")
        if joined.__class__.__name__ == "JoinResponse":
            raise RuntimeError("remote room join unexpectedly succeeded")
        # Even a caller bypassing nginx cannot make Synapse fetch remote media.
        request = urllib.request.Request(
            f"http://127.0.0.1:{synapse_port}/_matrix/client/v1/media/download/matrix.org/test",
            headers={"Authorization": "Bearer " + user_tokens["infra-alerts"]},
        )
        try:
            urllib.request.urlopen(request, timeout=2)
        except urllib.error.HTTPError as error:
            assert error.code == 403
        else:
            raise RuntimeError("Synapse accepted a foreign media origin")
        # Reopen the same crypto store and retain identity across a process restart.
        fingerprint = bot.olm.account.identity_keys["ed25519"]
        await bot.close()
        restarted = AsyncClient(
            f"http://127.0.0.1:{proxy_port}",
            bot.user_id,
            device_id=bot.device_id,
            store_path=str(directory / "infra-alerts"),
            config=AsyncClientConfig(encryption_enabled=True, store_sync_tokens=True),
        )
        restarted.restore_login(bot.user_id, bot.device_id, user_tokens["infra-alerts"])
        clients[0] = restarted
        assert restarted.olm.account.identity_keys["ed25519"] == fingerprint
        await restarted.sync(full_state=True)
        sent = await restarted.room_send(
            room,
            "m.room.message",
            {"msgtype": "m.text", "body": "After restart"},
            tx_id="after-restart",
        )
        assert isinstance(sent, RoomSendResponse)
        for attempt in range(10):
            await owner.sync(timeout=100)
            if "After restart" in decrypted:
                break
            await asyncio.sleep(0.1)
        assert "After restart" in decrypted
        # Exercise the production snapshot and offline verifier against real DBs.
        state = directory / "infra-alerts"
        queue = Queue(state / "queue.sqlite")
        queue.put("test", "undelivered", "Pending alert survives recovery")
        snapshot_crypto(restarted, state, state / "backups")
        dumps = directory / "dumps"
        dumps.mkdir()
        abandoned = dumps / "stage-abandoned"
        abandoned.mkdir()
        credentials = directory / "backup-credentials"
        credentials.mkdir()
        for database in ("synapse", "mas"):
            (credentials / (database + "-password")).write_text("synthetic")
        backup_environment = dict(
            os.environ,
            MATRIX_DUMPS_DIR=str(dumps),
            MATRIX_SECRET_DIR=str(credentials),
            MATRIX_DB_HOST="127.0.0.1",
            MATRIX_DB_PORT=str(pg_port),
        )
        subprocess.run(
            [sys.executable, str(Path(__file__).resolve().parents[1] / "backup.py")],
            env=backup_environment,
            capture_output=True,
            check=True,
        )
        assert not abandoned.exists()
        work = directory / "verify"
        work.mkdir()
        environment = dict(
            os.environ,
            MATRIX_RESTORE_DUMPS=str(dumps),
            MATRIX_RESTORE_WORK=str(work),
            MATRIX_RESTORE_MEDIA=str(directory / "media"),
            MATRIX_RESTORE_RELAY=str(state / "backups"),
        )
        verified = subprocess.run(
            [sys.executable, str(Path(__file__).resolve().parents[1] / "restore.py")],
            env=environment,
            capture_output=True,
            check=True,
        )
        print(verified.stdout.decode().strip())
        print(
            "PASS: MAS sessions, encrypted delivery/decryption, pinned devices, crypto restart and restore, forbidden routes, remote media and join rejection"
        )
        await qualify_relay(
            directory,
            restarted,
            owner,
            user_tokens["infra-alerts"],
            room,
            decrypted,
            proxy_port,
        )
    finally:
        for client in clients:
            await client.close()


def main():
    source = Path(__file__).resolve().parents[1]
    processes = []
    with tempfile.TemporaryDirectory(prefix="matrix-integration-") as temporary:
        directory = Path(temporary)
        pg_port, synapse_port, mas_port, proxy_port = [port() for _ in range(4)]
        # DockerTools exposes executables through /bin symlinks. PostgreSQL
        # locates its share directory relative to argv[0], so its native bin
        # directory must precede that symlink directory in the container PATH.
        runtime_bin = directory / "bin"
        runtime_bin.mkdir()
        initdb = Path(shutil.which("initdb")).resolve()
        (runtime_bin / "initdb").symlink_to(initdb)
        container_environment = dict(
            os.environ, PATH=f"{initdb.parent}:{runtime_bin}:{os.environ['PATH']}"
        )
        with tempfile.TemporaryDirectory(dir=directory) as probe:
            qualified = subprocess.run(
                ["initdb", "-D", probe + "/data", "--auth", "trust", "--locale", "C"],
                env=container_environment,
                capture_output=True,
            )
            if qualified.returncode:
                raise RuntimeError("PostgreSQL container PATH qualification failed")
        print("PASS: PostgreSQL initializes with the container executable layout")
        postgres_data = directory / "postgres"
        run(
            [
                "initdb",
                "-D",
                str(postgres_data),
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

        def start(argv, name):
            log = (directory / (name + ".log")).open("wb")
            process = subprocess.Popen(argv, stdout=log, stderr=log)
            log.close()
            processes.append(process)
            return process

        start(
            [
                "postgres",
                "-D",
                str(postgres_data),
                "-h",
                "127.0.0.1",
                "-p",
                str(pg_port),
                "-k",
                str(directory),
            ],
            "postgres",
        )
        try:
            for attempt in range(100):
                if (
                    subprocess.run(
                        ["pg_isready", "-h", "127.0.0.1", "-p", str(pg_port)],
                        capture_output=True,
                    ).returncode
                    == 0
                ):
                    break
                time.sleep(0.1)
            pg = [
                "psql",
                "-h",
                "127.0.0.1",
                "-p",
                str(pg_port),
                "-U",
                "postgres",
                "-v",
                "ON_ERROR_STOP=1",
            ]
            run(
                pg,
                b"CREATE USER synapse; CREATE USER mas; CREATE DATABASE synapse OWNER synapse; CREATE DATABASE mas OWNER mas;",
            )
            mas = yaml.safe_load(run(["mas-cli", "config", "generate"]))
            mas["http"] = {
                "public_base": f"http://127.0.0.1:{mas_port}/",
                "issuer": f"http://127.0.0.1:{mas_port}/",
                "listeners": [
                    {
                        "name": "web",
                        "resources": [
                            {"name": n}
                            for n in (
                                "discovery",
                                "human",
                                "oauth",
                                "compat",
                                "graphql",
                                "assets",
                            )
                        ],
                        "binds": [{"host": "127.0.0.1", "port": mas_port}],
                    }
                ],
            }
            mas["database"] = {
                "host": "127.0.0.1",
                "port": pg_port,
                "username": "mas",
                "database": "mas",
                "ssl_mode": "disable",
            }
            mas["matrix"] = {
                "kind": "synapse",
                "homeserver": "matrix.fahrican.com",
                "endpoint": f"http://127.0.0.1:{synapse_port}",
                "secret": "synthetic-shared-secret",
            }
            mas["passwords"]["enabled"] = False
            (directory / "mas.yaml").write_text(yaml.safe_dump(mas))
            run(["mas-cli", "config", "check", "--config", str(directory / "mas.yaml")])
            start(["mas-cli", "server", "--config", str(directory / "mas.yaml")], "mas")
            signing = directory / "signing.key"
            signing.write_text(
                "ed25519 test "
                + base64.b64encode(os.urandom(32)).decode().rstrip("=")
                + "\n"
            )
            synapse = {
                "server_name": "matrix.fahrican.com",
                "report_stats": False,
                "pid_file": str(directory / "synapse.pid"),
                "public_baseurl": f"http://127.0.0.1:{proxy_port}/",
                "signing_key_path": str(signing),
                "media_store_path": str(directory / "media"),
                "listeners": [
                    {
                        "port": synapse_port,
                        "bind_addresses": ["127.0.0.1"],
                        "type": "http",
                        "resources": [{"names": ["client"]}],
                    }
                ],
                "federation_domain_whitelist": [],
                "trusted_key_servers": [],
                "url_preview_enabled": False,
                "matrix_authentication_service": {
                    "enabled": True,
                    "endpoint": f"http://127.0.0.1:{mas_port}/",
                    "secret": "synthetic-shared-secret",
                },
                "database": {
                    "name": "psycopg2",
                    "args": {
                        "host": "127.0.0.1",
                        "port": pg_port,
                        "user": "synapse",
                        "database": "synapse",
                    },
                },
            }
            (directory / "synapse.yaml").write_text(yaml.safe_dump(synapse))
            start(
                [
                    "synapse_homeserver",
                    "--config-path",
                    str(directory / "synapse.yaml"),
                ],
                "synapse",
            )
            config = (
                (source / "nginx.conf")
                .read_text()
                .replace("listen 8080", f"listen {proxy_port}")
            )
            config = config.replace(
                "matrix-synapse:8008", f"127.0.0.1:{synapse_port}"
            ).replace("matrix-mas:8080", f"127.0.0.1:{mas_port}")
            config = (
                config.replace("/tmp/nginx.pid", str(directory / "nginx.pid"))
                .replace("/tmp/client-body", str(directory / "client-body"))
                .replace("/tmp/proxy", str(directory / "proxy"))
            )
            config = config.replace("@elementRoot@", str(directory)).replace(
                "/run/matrix/element.json", str(directory / "element.json")
            )
            config = config.replace(
                "/etc/ssl/certs/ca-bundle.crt", os.environ["SSL_CERT_FILE"]
            )
            (directory / "nginx.conf").write_text(config)
            run(["nginx", "-t", "-c", str(directory / "nginx.conf")])
            start(
                ["nginx", "-c", str(directory / "nginx.conf"), "-g", "daemon off;"],
                "nginx",
            )
            for attempt in range(120):
                try:
                    if (
                        http(f"http://127.0.0.1:{proxy_port}/_matrix/client/versions")[
                            0
                        ]
                        == 200
                        and http(
                            f"http://127.0.0.1:{mas_port}/.well-known/openid-configuration"
                        )[0]
                        == 200
                    ):
                        break
                except Exception:
                    pass
                if any(process.poll() is not None for process in processes):
                    for name, process in zip(
                        ("postgres", "mas", "synapse", "nginx"), processes
                    ):
                        if process.poll() is not None:
                            tail = (directory / (name + ".log")).read_text()[-3000:]
                            tail = re.sub(r"mct_[A-Za-z0-9_-]+", "[test token]", tail)
                            raise RuntimeError(
                                name + " exited during synthetic test startup: " + tail
                            )
                time.sleep(0.5)
            else:
                raise RuntimeError("test services did not become ready")
            asyncio.run(qualify(directory, pg_port, synapse_port, mas_port, proxy_port))
        finally:
            for process in reversed(processes):
                process.terminate()
            for process in reversed(processes):
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


if __name__ == "__main__":
    main()

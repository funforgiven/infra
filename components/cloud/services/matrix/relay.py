#!/usr/bin/env python3
"""Private durable alert intake and fail-closed encrypted Matrix delivery."""

import asyncio
import hashlib
import hmac
import json
import logging
import os
import sqlite3
import time
from pathlib import Path

from aiohttp import web
from nio import (
    AsyncClient,
    AsyncClientConfig,
    JoinedMembersResponse,
    KeysQueryResponse,
    KeysUploadResponse,
    RoomSendResponse,
    SyncResponse,
)

LOG = logging.getLogger("matrix-relay")
RECOVERY_CANARY = "Matrix crypto recovery qualification"


def snapshot_crypto(client, state, recovery):
    from nio.crypto import InboundGroupSession, OutboundGroupSession

    recovery.mkdir(exist_ok=True)
    keys = client.olm.account.identity_keys
    # Persist a session before backing up, then prove that the restored session
    # can decrypt its ciphertext without contacting any server.
    outgoing = OutboundGroupSession()
    room = "!recovery-canary:matrix.fahrican.com"
    incoming = InboundGroupSession(
        outgoing.session_key, keys["ed25519"], keys["curve25519"], room
    )
    client.olm.store.save_inbound_group_session(incoming)
    outgoing.shared = True
    ciphertext = outgoing.encrypt(RECOVERY_CANARY)
    for source in list(state.glob("*.db")) + list(state.glob("*.sqlite")):
        destination = recovery / source.name
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        with sqlite3.connect(source) as origin, sqlite3.connect(temporary) as target:
            origin.backup(target)
        temporary.replace(destination)
    identity = {
        "user_id": client.user_id,
        "device_id": client.device_id,
        "ed25519": keys["ed25519"],
        "canary": {
            "room_id": room,
            "sender_key": keys["curve25519"],
            "session_id": incoming.id,
            "ciphertext": ciphertext,
        },
    }
    temporary = recovery / "identity.json.tmp"
    temporary.write_text(json.dumps(identity))
    temporary.replace(recovery / "identity.json")


class Queue:
    def __init__(self, path):
        self.db = sqlite3.connect(path)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("PRAGMA secure_delete=ON")
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS events "
            "(id TEXT PRIMARY KEY, body TEXT NOT NULL, body_hash TEXT NOT NULL, created REAL NOT NULL, delivered REAL)"
        )

    def put(self, producer, event_id, body):
        return self.put_many(producer, [(event_id, body)])[0]

    def put_many(self, producer, batch):
        keys = []
        with self.db:
            for event_id, body in batch:
                key = hashlib.sha256((producer + "\0" + event_id).encode()).hexdigest()
                body_hash = hashlib.sha256(body.encode()).hexdigest()
                existing = self.db.execute(
                    "SELECT body_hash FROM events WHERE id=?", (key,)
                ).fetchone()
                if existing and existing[0] != body_hash:
                    raise ValueError("event ID reused with different content")
                self.db.execute(
                    "INSERT OR IGNORE INTO events VALUES (?, ?, ?, ?, NULL)",
                    (key, body, body_hash, time.time()),
                )
                keys.append(key)
        return keys

    def pending(self):
        return self.db.execute(
            "SELECT id, body FROM events WHERE delivered IS NULL "
            "ORDER BY created LIMIT 1"
        ).fetchone()

    def delivered(self, event_id):
        with self.db:
            self.db.execute(
                "UPDATE events SET delivered=?, body='' WHERE id=?",
                (time.time(), event_id),
            )
        self.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    def stats(self):
        count, oldest = self.db.execute(
            "SELECT COUNT(*), MIN(created) FROM events WHERE delivered IS NULL"
        ).fetchone()
        return count, 0 if oldest is None else max(0, time.time() - oldest)

    def snapshot(self, destination):
        # SQLite online backup includes committed WAL contents without stopping intake.
        with sqlite3.connect(destination) as target:
            self.db.backup(target)


def messages(payload, producer, path):
    if path == "/alertmanager":
        alerts = payload.get("alerts")
        if not isinstance(alerts, list) or not 1 <= len(alerts) <= 100:
            raise ValueError("expected 1–100 alerts")
        result = []
        for alert in alerts:
            status = alert["status"]
            if status not in ("firing", "resolved"):
                raise ValueError("invalid alert status")
            labels, annotations = alert.get("labels", {}), alert.get("annotations", {})
            event_id = json.dumps(
                [
                    alert["fingerprint"],
                    status,
                    alert["startsAt"],
                    alert.get("endsAt") if status == "resolved" else None,
                ]
            )
            # Repeats remain useful; bucket repeated firing notifications by six hours.
            if status == "firing":
                event_id += ":" + str(int(time.time() // (6 * 3600)))
            text = f"[{status.upper()}] {labels.get('severity', 'unknown')}: {labels.get('alertname', 'Alert')}"
            text += (
                "\n"
                + annotations.get("summary", "")
                + "\n"
                + annotations.get("description", "")
            )
            text += "\n" + json.dumps(labels, sort_keys=True)
            result.append((event_id, text[:16000]))
        return result
    if payload.get("producer_id") != producer:
        raise ValueError("producer mismatch")
    fields = ("event_id", "host", "unit", "severity", "message")
    if any(
        not isinstance(payload.get(key), str)
        or not payload[key]
        or len(payload[key]) > 4096
        for key in fields
    ):
        raise ValueError("invalid notification fields")
    return [
        (
            payload["event_id"],
            f"[{payload['severity'].upper()}] {payload['host']}: {payload['unit']}\n{payload['message']}",
        )
    ]


def authenticate(header, producers, path):
    for producer, item in producers.items():
        if path in item["paths"] and hmac.compare_digest(
            header, "Bearer " + item["token"]
        ):
            return producer
    return None


def check_room(client, room_id, allowed_users, pins):
    room = client.rooms.get(room_id)
    if room is None or not room.encrypted:
        raise ValueError("destination is not a synced encrypted room")
    if set(room.users) - set(allowed_users):
        raise ValueError("unexpected room member")
    if set(allowed_users) - set(room.users):
        raise ValueError("intended recipient has not joined")
    for user_id in room.users:
        devices = list(client.device_store.active_user_devices(user_id))
        if user_id != client.user_id and not devices:
            raise ValueError("recipient has no queried devices")
        for device in devices:
            if user_id == client.user_id and device.id == client.device_id:
                continue
            fingerprint = pins.get(user_id, {}).get(device.id)
            if fingerprint != device.ed25519:
                raise ValueError("unapproved device")
            client.verify_device(device)


async def serve(config_file, state):
    config_path = Path(config_file)
    state.mkdir(parents=True, exist_ok=True)
    queue = Queue(state / "queue.sqlite")
    client = None
    failures = 0
    last_delivery = 0
    stopping = asyncio.Event()
    state_lock = asyncio.Lock()

    def config():
        return json.loads(config_path.read_text())

    async def intake(request):
        settings = config()
        producer = authenticate(
            request.headers.get("Authorization", ""),
            settings["producers"],
            request.path,
        )
        if producer is None:
            raise web.HTTPUnauthorized()
        try:
            payload = await request.json()
            batch = messages(payload, producer, request.path)
            # Validate the entire batch before accepting any event.
            queue.put_many(producer, batch)
        except (ValueError, KeyError, TypeError):
            raise web.HTTPBadRequest(text="Invalid notification") from None
        except sqlite3.Error:
            raise web.HTTPServiceUnavailable(text="Durable queue unavailable") from None
        return web.json_response({"accepted": len(batch)}, status=202)

    async def health(_request):
        return web.json_response({"queue": "available"})

    async def metrics(_request):
        count, age = queue.stats()
        text = f"matrix_relay_queue_depth {count}\nmatrix_relay_oldest_seconds {age}\n"
        text += f"matrix_relay_delivery_failures_total {failures}\nmatrix_relay_last_delivery_seconds {last_delivery}\n"
        return web.Response(text=text, content_type="text/plain")

    async def backup(_request):
        # Only the pod's loopback backup hook can create a queue snapshot.
        async with state_lock:
            if client is None or client.olm is None:
                raise web.HTTPServiceUnavailable(text="Crypto identity is not enrolled")
            snapshot_crypto(client, state, state / "backups")
        return web.Response(text="ok")

    async def deliver():
        nonlocal client, failures, last_delivery
        heartbeat_at = 0
        while not stopping.is_set():
            try:
                settings = config()
                if not settings.get("access_token"):
                    await asyncio.sleep(5)
                    continue
                identity = (
                    settings["user_id"],
                    settings["device_id"],
                    settings["access_token"],
                )
                if client is None or identity != (
                    client.user_id,
                    client.device_id,
                    client.access_token,
                ):
                    if client:
                        await client.close()
                    client = AsyncClient(
                        settings["homeserver"],
                        identity[0],
                        device_id=identity[1],
                        store_path=str(state),
                        config=AsyncClientConfig(
                            encryption_enabled=True, store_sync_tokens=True
                        ),
                    )
                    client.restore_login(*identity)
                async with state_lock:
                    synced = await client.sync(
                        timeout=1000, full_state=not client.rooms
                    )
                    if not isinstance(synced, SyncResponse):
                        raise ValueError("sync failed")
                    # Refresh all members and device keys before deciding which devices receive keys.
                    for room_id in (settings["room_id"], settings["canary_room_id"]):
                        if not isinstance(
                            await client.joined_members(room_id), JoinedMembersResponse
                        ):
                            raise ValueError("member refresh failed")
                    if client.should_upload_keys:
                        if not isinstance(
                            await client.keys_upload(), KeysUploadResponse
                        ):
                            raise ValueError("key upload failed")
                    if client.should_query_keys:
                        if not isinstance(await client.keys_query(), KeysQueryResponse):
                            raise ValueError("device refresh failed")
                    # Delivery health includes the intended recipients even when
                    # the queue is empty. An absent member or unapproved device
                    # must stop both alert delivery and the independent heartbeat.
                    check_room(
                        client,
                        settings["room_id"],
                        settings["allowed_users"],
                        settings["trusted_devices"],
                    )
                    pending = queue.pending()
                    if pending:
                        room = settings["room_id"]
                        response = await client.room_send(
                            room,
                            "m.room.message",
                            {"msgtype": "m.text", "body": pending[1]},
                            tx_id=pending[0],
                            ignore_unverified_devices=False,
                        )
                        if not isinstance(response, RoomSendResponse):
                            raise ValueError("encrypted send failed")
                        queue.delivered(pending[0])
                        last_delivery = time.time()
                    if time.time() - heartbeat_at >= 60:
                        room = settings["canary_room_id"]
                        check_room(client, room, [client.user_id], {})
                        response = await client.room_send(
                            room,
                            "m.room.message",
                            {"msgtype": "m.notice", "body": "Delivery canary"},
                            tx_id="canary-" + str(int(time.time() // 60)),
                        )
                        if not isinstance(response, RoomSendResponse):
                            raise ValueError("encrypted canary failed")
                        from aiohttp import ClientSession

                        heartbeat = settings.get("heartbeat")
                        if not heartbeat:
                            raise ValueError("independent heartbeat not enrolled")
                        async with ClientSession() as session:
                            async with session.post(
                                heartbeat["url"],
                                headers={
                                    "Authorization": "Bearer " + heartbeat["token"]
                                },
                            ) as response:
                                if response.status != 202:
                                    raise ValueError("independent heartbeat rejected")
                        heartbeat_at = time.time()

            except Exception as error:
                failures += 1
                # Exceptions can contain server responses or secrets. Log only their type.
                LOG.warning("Delivery paused (%s)", type(error).__name__)
                await asyncio.sleep(10)

    app = web.Application(client_max_size=256 * 1024)
    app.router.add_post("/alertmanager", intake)
    app.router.add_post("/notify", intake)
    app.router.add_get("/health", health)
    app.router.add_get("/metrics", metrics)
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    await web.TCPSite(
        runner, "0.0.0.0", int(os.environ.get("RELAY_PORT", "8080"))
    ).start()
    backup_app = web.Application()
    backup_app.router.add_post("/snapshot", backup)
    backup_runner = web.AppRunner(backup_app, access_log=None)
    await backup_runner.setup()
    await web.TCPSite(
        backup_runner, "127.0.0.1", int(os.environ.get("RELAY_BACKUP_PORT", "8081"))
    ).start()
    task = asyncio.create_task(deliver())
    import signal

    loop = asyncio.get_running_loop()
    for signum in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(signum, stopping.set)
    try:
        await stopping.wait()
    finally:
        task.cancel()
        if client:
            await client.close()
        await runner.cleanup()
        await backup_runner.cleanup()


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    os.umask(0o077)
    asyncio.run(
        serve(
            os.environ.get("RELAY_CONFIG", "/run/matrix/relay.json"),
            Path(os.environ.get("RELAY_STATE", "/var/lib/matrix/relay")),
        )
    )

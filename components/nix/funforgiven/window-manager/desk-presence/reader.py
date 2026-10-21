"""Relay an HA presence entity to Quickshell; never send HA service commands."""

import argparse
from contextlib import closing
import json
import logging
import os
from pathlib import Path
import subprocess
import time

import websocket

# Quickshell expires presence after a 45-second lease (PresencePolicy.qml).
# Refresh well inside it: a renewal waits for the next 10-second pong.
LEASE_REFRESH = 25


def state_value(state):
    value = state.get("state") if isinstance(state, dict) else None
    return value if value in ("on", "off") else "unknown"


def entity_update(event, entity):
    """Return the entity's new state from a subscribe_entities event, if any."""
    if not isinstance(event, dict):
        return None
    if entity in event.get("r", ()):
        return "unknown"
    added = event.get("a", {}).get(entity)
    if isinstance(added, dict):
        return state_value({"state": added.get("s")})
    changed = event.get("c", {}).get(entity)
    if isinstance(changed, dict) and "s" in changed.get("+", {}):
        return state_value({"state": changed["+"]["s"]})
    return None


def relay(args, publish):
    token = (Path(os.environ["CREDENTIALS_DIRECTORY"]) / "ha-token").read_text().strip()
    if not token:
        raise ValueError("Empty credential")
    with closing(websocket.create_connection(args.url, timeout=10)) as connection:
        if json.loads(connection.recv()).get("type") != "auth_required":
            raise ValueError("Unexpected handshake")
        connection.send(json.dumps({"type": "auth", "access_token": token}))
        del token
        if json.loads(connection.recv()).get("type") != "auth_ok":
            raise ValueError("Authentication failed")
        # subscribe_entities delivers the entity's current state first and then
        # only its changes, so no separate snapshot is needed and the startup
        # race between subscribing and reading cannot drop an update.
        connection.send(json.dumps({"id": 1, "type": "subscribe_entities", "entity_ids": [args.entity]}))
        state = "unknown"
        ping_id = 1
        next_ping = time.monotonic()
        pending_ping = None
        next_refresh = None
        logging.info("Home Assistant connected")

        def update(value):
            nonlocal state, next_refresh
            state = value
            publish(state)
            next_refresh = time.monotonic() + LEASE_REFRESH

        while True:
            now = time.monotonic()
            if pending_ping is not None and now - pending_ping > 10:
                raise TimeoutError("Home Assistant heartbeat expired")
            if pending_ping is None and now >= next_ping:
                ping_id += 1
                connection.send(json.dumps({"id": ping_id, "type": "ping"}))
                pending_ping = now
            try:
                message = json.loads(connection.recv())
            except websocket.WebSocketTimeoutException:
                continue
            kind = message.get("type")
            if kind == "result":
                if not message.get("success"):
                    raise ValueError("Home Assistant request rejected")
            elif kind == "event" and message.get("id") == 1:
                value = entity_update(message.get("event"), args.entity)
                if value is None and next_refresh is None:
                    # The first event is the snapshot; a missing entity is unknown.
                    value = state
                if value is not None:
                    update(value)
            elif kind == "pong" and message.get("id") == ping_id:
                pending_ping = None
                next_ping = time.monotonic() + 10
                # Only a healthy connection renews Quickshell's presence lease;
                # changes are published as soon as they arrive.
                if next_refresh is not None and time.monotonic() >= next_refresh:
                    update(state)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--entity", required=True)
    parser.add_argument("--quickshell", required=True)
    parser.add_argument("--config", required=True)
    args = parser.parse_args()
    if not args.url.startswith("wss://"):
        parser.error("Home Assistant must use a verified TLS connection (wss://)")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    last_state = None

    def publish(state):
        nonlocal last_state
        if state != last_state:
            logging.info("Desk presence: %s", state)
            last_state = state
        try:
            result = subprocess.run(
                [args.quickshell, "-c", args.config, "ipc", "call", "amoled", "updatePresence", state],
                timeout=3, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
            )
            if result.returncode:
                logging.warning("Quickshell unavailable; retrying on next heartbeat")
        except (OSError, subprocess.TimeoutExpired):
            logging.warning("Quickshell IPC failed; retrying on next heartbeat")

    while True:
        publish("unknown")
        try:
            relay(args, publish)
        except (OSError, ValueError, TimeoutError, websocket.WebSocketException) as error:
            # Never log responses or exception bodies: they may contain auth data.
            logging.warning("Presence connection interrupted (%s); using idle fallback", type(error).__name__)
            publish("unknown")
            time.sleep(5)


if __name__ == "__main__":
    main()

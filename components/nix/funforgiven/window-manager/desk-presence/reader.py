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


def state_value(state):
    value = state.get("state") if isinstance(state, dict) else None
    return value if value in ("on", "off") else "unknown"


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
        # Subscribe before taking the initial snapshot, so changes during
        # connection setup cannot be missed. Process messages in wire order.
        connection.send(json.dumps({"id": 1, "type": "subscribe_events", "event_type": "state_changed"}))
        connection.send(json.dumps({"id": 2, "type": "get_states"}))
        state = "unknown"
        ping_id = 2
        next_ping = time.monotonic()
        pending_ping = None
        logging.info("Home Assistant connected")
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
                if message.get("id") == 2:
                    state = state_value(next((s for s in message["result"] if s["entity_id"] == args.entity), None))
                    publish(state)
            elif kind == "event":
                data = message.get("event", {}).get("data", {})
                if data.get("entity_id") == args.entity:
                    state = state_value(data.get("new_state"))
                    publish(state)
            elif kind == "pong" and message.get("id") == ping_id:
                pending_ping = None
                next_ping = time.monotonic() + 10
                publish(state)


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

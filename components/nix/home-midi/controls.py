"""Control the loft light and AC airflow from two RODECaster MIDI pads."""

import argparse
import json
import logging
import os
from pathlib import Path
import queue
import re
import signal
import threading
import time
import urllib.error
import urllib.parse
import urllib.request


ACTIONS = {106: "loft-light", 107: "loft-airflow"}
LABELS = {"loft-light": "Loft light toggle", "loft-airflow": "Loft AC comfort/swing"}
COOLDOWN = {"loft-light": 0.3, "loft-airflow": 2.0}
LOG = logging.getLogger("home-midi")


def midi_action(message):
    if message.type == "control_change" and message.channel == 15 and message.value > 0:
        return ACTIONS.get(message.control)
    return None


def select_port(names):
    matches = [name for name in names if re.fullmatch(
        r"RODECaster Duo:RODECaster Duo MIDI 1 \d+:\d+", name.replace("Ø", "O"))]
    return matches[0] if len(matches) == 1 else None


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # A toggle must never be replayed, or its capability sent to another host.
        return None


def load_webhooks():
    directory = Path(os.environ.get("CREDENTIALS_DIRECTORY", "/run/secrets"))
    name = "ha-webhooks" if "CREDENTIALS_DIRECTORY" in os.environ else "home-assistant-midi-webhooks"
    config = json.loads((directory / name).read_text())
    if set(config) != set(LABELS):
        raise ValueError("Expected exactly the two configured home controls")
    for value in config.values():
        url = urllib.parse.urlsplit(value)
        if (url.scheme != "https" or url.netloc != "home.fahrican.com"
                or url.query or url.fragment
                or not re.fullmatch(r"/api/webhook/[A-Za-z0-9_-]{40,}", url.path)):
            raise ValueError("Invalid home control endpoint")
    return config


def trigger(action, webhooks, dry_run=False, opener=None):
    if action not in LABELS:
        raise ValueError("Unknown home control")
    if dry_run:
        return {"action": action, "send": False}
    opener = opener or urllib.request.build_opener(NoRedirect())
    request = urllib.request.Request(webhooks[action], data=b"", method="POST")
    try:
        with opener.open(request, timeout=4) as response:
            if not 200 <= response.status < 300:
                raise ValueError("Home Assistant did not accept the command")
    except (urllib.error.URLError, OSError):
        # URL errors can contain the secret webhook path. Never log their body.
        raise ValueError("Home Assistant request failed; not retried because toggles may already have run") from None
    LOG.info("Requested %s", LABELS[action])
    return {"action": action, "submitted": True}


class Dispatcher:
    def __init__(self, stopped, send, clock=time.monotonic):
        self.stopped = stopped
        self.send = send
        self.clock = clock
        self.events = queue.Queue(maxsize=4)
        self.last_press = {}

    def receive(self, message):
        action = midi_action(message)
        if action is None or self.stopped.is_set():
            return
        now = self.clock()
        if now - self.last_press.get(action, float("-inf")) < COOLDOWN[action]:
            return
        self.last_press[action] = now
        try:
            self.events.put_nowait((action, now))
        except queue.Full:
            LOG.warning("Home controls busy; discarded pad press")

    def dispatch(self, action, received):
        if self.clock() - received > 3:
            LOG.warning("Expired %s; press the pad again", LABELS[action])
            return
        self.send(action)

    def work(self):
        while not self.stopped.is_set():
            try:
                event = self.events.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                self.dispatch(*event)
            except (ValueError, OSError):
                LOG.warning("Home command failed; see HA automation traces before repeating a toggle")


def listen(webhooks):
    import mido

    backend = mido.Backend("mido.backends.rtmidi/LINUX_ALSA")
    stopped = threading.Event()
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, lambda *_: stopped.set())
    dispatcher = Dispatcher(stopped, lambda action: trigger(action, webhooks))
    worker = threading.Thread(target=dispatcher.work, daemon=True)
    worker.start()
    port = None
    try:
        LOG.info("Waiting for RODECaster Duo; channel 16, CC 106–107")
        while not stopped.is_set():
            name = select_port(backend.get_input_names())
            if port is not None and (port.closed or port.name != name):
                port.close()
                port = None
                LOG.info("Duo disconnected; waiting for reconnect")
            if port is None and name is not None:
                try:
                    port = backend.open_input(name, callback=dispatcher.receive)
                    LOG.info("Listening on %s", name)
                except (OSError, RuntimeError):
                    LOG.warning("Cannot open Duo MIDI port; will reconnect")
            stopped.wait(1)
    finally:
        stopped.set()
        if port is not None:
            port.close()
        worker.join(timeout=5)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("listen", help="Listen for the two home-control MIDI pads")
    action = commands.add_parser("trigger", help="Send one home-control command")
    action.add_argument("action", choices=LABELS)
    action.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        if args.command == "trigger" and args.dry_run:
            print(json.dumps(trigger(args.action, {}, dry_run=True)))
        else:
            webhooks = load_webhooks()
            if args.command == "listen":
                listen(webhooks)
            else:
                print(json.dumps(trigger(args.action, webhooks)))
    except (ValueError, OSError):
        LOG.error("Home control failed; check credential deployment, connectivity and HA automation traces")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

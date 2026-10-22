"""Toggle the loft light and AC airflow through Home Assistant webhooks (CC 106–107)."""

import json
import logging
import os
from pathlib import Path
import queue
import re
import time
import urllib.error
import urllib.parse
import urllib.request


ACTIONS = {106: "loft-light", 107: "loft-airflow"}
LABELS = {"loft-light": "Loft light toggle", "loft-airflow": "Loft AC comfort/swing"}
COOLDOWN = {"loft-light": 0.3, "loft-airflow": 2.0}
LOG = logging.getLogger("duo-midi.home")


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
    controls = ACTIONS

    def __init__(self, stopped, send, clock=time.monotonic):
        self.stopped = stopped
        self.send = send
        self.clock = clock
        self.events = queue.Queue(maxsize=4)
        self.last_press = {}

    def receive(self, control):
        action = ACTIONS.get(control)
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

"""Act on RODECaster Duo SMART pads: route focused-app audio or call Home Assistant."""

import argparse
import json
import logging
import re
import signal
import subprocess
import threading

import audio
import home


MIDI_CHANNEL = 15  # MIDI's displayed channel 16 is zero-based in Mido.
LOG = logging.getLogger("duo-midi")


def select_port(names):
    matches = [name for name in names if re.fullmatch(
        r"RODECaster Duo:RODECaster Duo MIDI 1 \d+:\d+", name.replace("Ø", "O"))]
    return matches[0] if len(matches) == 1 else None


def receiver(dispatchers):
    """Return the MIDI callback that hands each pad press to the dispatcher owning its CC."""
    table = {control: dispatcher for dispatcher in dispatchers for control in dispatcher.controls}

    def receive(message):
        if (message.type == "control_change" and message.channel == MIDI_CHANNEL
                and message.value > 0 and message.control in table):
            table[message.control].receive(message.control)

    return receive


def dispatchers(stopped):
    # Each group has its own queue and worker, so a slow audio move never delays
    # (and expires) a light toggle, and a slow Home Assistant never delays routing.
    groups = [audio.Dispatcher(stopped)]
    try:
        webhooks = home.load_webhooks()
        groups.append(home.Dispatcher(stopped, lambda action: home.trigger(action, webhooks)))
    except (ValueError, OSError):
        # Audio routing keeps working; never log details that could hold a webhook ID.
        LOG.error("Home controls disabled; check the webhook credential deployment")
    return groups


def listen():
    import mido

    backend = mido.Backend("mido.backends.rtmidi/LINUX_ALSA")
    stopped = threading.Event()
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, lambda *_: stopped.set())
    groups = dispatchers(stopped)
    receive = receiver(groups)
    workers = [threading.Thread(target=group.work, daemon=True) for group in groups]
    for worker in workers:
        worker.start()
    port = None
    try:
        LOG.info("Waiting for RODECaster Duo; channel 16, CC %s",
                 ", ".join(str(control) for group in groups for control in group.controls))
        while not stopped.is_set():
            name = select_port(backend.get_input_names())
            if port is not None and (port.closed or port.name != name):
                port.close()
                port = None
                LOG.info("Duo disconnected; waiting for reconnect")
            if port is None and name is not None:
                try:
                    port = backend.open_input(name, callback=receive)
                    LOG.info("Listening on %s", name)
                except (OSError, RuntimeError) as error:
                    LOG.warning("Cannot open Duo MIDI port: %s", error)
            stopped.wait(1)
    finally:
        stopped.set()
        if port is not None:
            port.close()
        for worker in workers:
            # Let an in-flight webhook finish rather than cutting it off mid-toggle.
            worker.join(timeout=5)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("listen", help="Listen for the Duo routing and home-control pads")
    route = commands.add_parser("route", help="Route the currently focused app once")
    route.add_argument("channel", choices=audio.LABELS)
    route.add_argument("--dry-run", action="store_true", help="Show matching streams without moving them")
    trigger = commands.add_parser("trigger", help="Send one home-control command")
    trigger.add_argument("action", choices=home.LABELS)
    trigger.add_argument("--dry-run", action="store_true", help="Validate the action without sending it")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if args.command == "listen":
        listen()
    elif args.command == "route":
        try:
            print(json.dumps(audio.route(audio.capture_focus(), args.channel, args.dry_run)))
        except (ValueError, OSError, subprocess.SubprocessError) as error:
            LOG.error("%s", error)
            return 1
    else:
        try:
            webhooks = {} if args.dry_run else home.load_webhooks()
            print(json.dumps(home.trigger(args.action, webhooks, args.dry_run)))
        except (ValueError, OSError):
            LOG.error("Home control failed; check credential deployment, connectivity and HA automation traces")
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

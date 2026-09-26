"""Route the focused Niri application's playback from four RODECaster MIDI pads."""

import argparse
from dataclasses import dataclass
import html
import json
import logging
from pathlib import Path
import queue
import re
import signal
import subprocess
import threading
import time


CHANNELS = {102: "system", 103: "game", 104: "voice", 105: "music"}
LABELS = {"system": "System", "game": "Game", "voice": "Voice Chat", "music": "Music"}
MIDI_CHANNEL = 15  # MIDI's displayed channel 16 is zero-based in Mido.
LOG = logging.getLogger("audio-midi")


def normalized_id(value):
    return str(value or "").strip().lower().removesuffix(".desktop")


def positive_int(value):
    try:
        number = int(str(value))
        return number if number > 0 else None
    except (TypeError, ValueError):
        return None


def process_info(pid):
    """Return parent PID and start time; start time protects against PID reuse."""
    if not positive_int(pid):
        return None
    try:
        fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        return int(fields[1]), int(fields[19])
    except (OSError, ValueError, IndexError):
        return None


@dataclass(frozen=True)
class Focus:
    window_id: int
    app_id: str
    pid: int | None
    start_time: int | None
    other_app_pids: frozenset


def focus_from_windows(windows, read_process=process_info):
    focused = [w for w in windows if w.get("is_focused") is True]
    if len(focused) != 1:
        raise ValueError("No focused application window")
    window = focused[0]
    app_id = str(window.get("app_id") or "")
    pid = positive_int(window.get("pid"))
    process = read_process(pid)
    others = frozenset(
        positive_int(w.get("pid")) for w in windows
        if positive_int(w.get("pid")) != pid
        and (not app_id or normalized_id(w.get("app_id")) != normalized_id(app_id))
    ) - {None}
    if not app_id and process is None:
        raise ValueError("The focused window has no usable application identity")
    return Focus(window["id"], app_id, pid, process[1] if process else None, others)


def capture_focus():
    result = subprocess.run(
        ["niri", "msg", "--json", "windows"], check=True,
        capture_output=True, text=True, timeout=1,
    )
    return focus_from_windows(json.loads(result.stdout))


def belongs_to_focus(pid, focus, read_process):
    seen = set()
    for _ in range(64):
        if not pid or pid in seen or pid in focus.other_app_pids:
            return False
        info = read_process(pid)
        if info is None:
            return False
        if pid == focus.pid:
            return focus.start_time is not None and info[1] == focus.start_time
        seen.add(pid)
        pid = info[0]
    return False


def matching_streams(graph, focus, read_process=process_info):
    if focus.start_time is not None:
        current = read_process(focus.pid)
        if current is None or current[1] != focus.start_time:
            raise ValueError("The focused application exited before routing")
    clients = {
        str(obj["id"]): obj.get("info", {}).get("props", {})
        for obj in graph if obj.get("type") == "PipeWire:Interface:Client"
    }
    selected = []
    for node in graph:
        if node.get("type") != "PipeWire:Interface:Node":
            continue
        props = node.get("info", {}).get("props", {})
        if props.get("media.class") != "Stream/Output/Audio":
            continue
        if ("funforgiven.audio.kind" in props or "funforgiven.audio.channel" in props
                or str(props.get("node.name", "")).startswith("funforgiven.audio.channel.")
                or props.get("stream.monitor") in (True, "true", "yes", "1")
                or props.get("node.monitor") in (True, "true", "yes", "1")):
            continue
        # ALSA clients put process identity on the Client, not the stream Node.
        identity = clients.get(str(props.get("client.id")), {}) | props
        app_id = normalized_id(focus.app_id)
        identity_match = bool(app_id) and any(
            normalized_id(identity.get(key)) == app_id
            for key in ("application.id", "application.process.binary")
        )
        process_match = any(
            belongs_to_focus(positive_int(identity.get(key)), focus, read_process)
            for key in ("application.process.id", "pipewire.sec.pid")
        )
        if not (identity_match or process_match):
            continue
        if "object.serial" not in props:
            continue
        selected.append({"id": node["id"], "serial": props["object.serial"]})
    return selected


def notify(message, error=False):
    try:
        subprocess.run(
            ["notify-send", "--app-name=Audio routing", "--expire-time=2500",
             "--urgency=" + ("normal" if error else "low"), "Audio routing", html.escape(message)],
            timeout=2, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        pass


def route(focus, channel, dry_run=False):
    if channel not in LABELS:
        raise ValueError("Unknown audio channel")
    result = subprocess.run(["pw-dump"], check=True, capture_output=True, text=True, timeout=5)
    streams = matching_streams(json.loads(result.stdout), focus)
    if not streams:
        raise ValueError(f"No active playback for {focus.app_id or 'the focused app'}; start audio first")
    if dry_run:
        return {"app_id": focus.app_id, "window_id": focus.window_id, "channel": channel, "streams": streams}
    failures = 0
    for stream in streams:
        try:
            # The existing helper revalidates IDs/serials and confirms each move.
            subprocess.run(
                ["funforgiven-audioctl", "move-stream", str(stream["id"]), str(stream["serial"]), channel],
                check=True, capture_output=True, text=True, timeout=15,
            )
        except (OSError, subprocess.SubprocessError) as error:
            failures += 1
            LOG.warning("Stream %s routing failed: %s", stream["id"], error)
    if failures:
        raise ValueError(f"Moved {len(streams) - failures}/{len(streams)} streams; playback changed or routing failed")
    message = f"{focus.app_id or 'Focused app'} → {LABELS[channel]}"
    LOG.info("%s (%d streams)", message, len(streams))
    notify(message)
    return {"app_id": focus.app_id, "channel": channel, "moved": len(streams)}


def midi_target(message):
    if (message.type == "control_change" and message.channel == MIDI_CHANNEL
            and message.value > 0):
        return CHANNELS.get(message.control)
    return None


def select_port(names):
    matches = [name for name in names if re.fullmatch(
        r"RODECaster Duo:RODECaster Duo MIDI 1 \d+:\d+", name.replace("Ø", "O"))]
    return matches[0] if len(matches) == 1 else None


class Dispatcher:
    def __init__(self, stopped, capture=capture_focus, move=route, report=notify):
        self.stopped = stopped
        self.capture = capture
        self.move = move
        self.report = report
        self.events = queue.Queue(maxsize=8)
        self.last_press = {}

    def receive(self, message):
        channel = midi_target(message)
        if channel is None or self.stopped.is_set():
            return
        now = time.monotonic()
        if now - self.last_press.get(channel, float("-inf")) < 0.15:
            return
        self.last_press[channel] = now
        try:
            # Capture in the MIDI callback, before a previous move can delay us.
            focus = self.capture()
            self.events.put_nowait((focus, channel, now))
        except (ValueError, OSError, subprocess.SubprocessError, queue.Full) as error:
            LOG.warning("Cannot queue MIDI route: %s", error)
            self.report("Cannot route the focused app; the desktop is unavailable or routing is busy", error=True)

    def work(self):
        while not self.stopped.is_set():
            try:
                focus, channel, received = self.events.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                if time.monotonic() - received > 5:
                    raise ValueError("Routing request expired; press the pad again")
                self.move(focus, channel)
            except (ValueError, OSError, subprocess.SubprocessError) as error:
                LOG.warning("Cannot route app: %s", error)
                self.report(str(error), error=True)


def listen():
    import mido

    backend = mido.Backend("mido.backends.rtmidi/LINUX_ALSA")
    stopped = threading.Event()
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, lambda *_: stopped.set())
    dispatcher = Dispatcher(stopped)
    worker = threading.Thread(target=dispatcher.work, daemon=True)
    worker.start()
    port = None
    try:
        LOG.info("Waiting for RODECaster Duo; channel 16, CC 102–105")
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
                except (OSError, RuntimeError) as error:
                    LOG.warning("Cannot open Duo MIDI port: %s", error)
            stopped.wait(1)
    finally:
        stopped.set()
        if port is not None:
            port.close()
        worker.join(timeout=2)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("listen", help="Listen for the four Duo MIDI routing pads")
    action = commands.add_parser("route", help="Route the currently focused app once")
    action.add_argument("channel", choices=LABELS)
    action.add_argument("--dry-run", action="store_true", help="Show matching streams without moving them")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        if args.command == "listen":
            listen()
        else:
            print(json.dumps(route(capture_focus(), args.channel, args.dry_run)))
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        LOG.error("%s", error)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

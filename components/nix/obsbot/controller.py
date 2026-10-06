"""JSON-lines camera helper used by the Quickshell popup; also a small CLI."""

import argparse
import fcntl
import json
import os
from pathlib import Path
import selectors
import signal
import sys
import tempfile
import time

from transport import Camera


IMAGE_CONTROLS = (
    "auto_exposure", "white_balance_automatic", "focus_automatic_continuous",
    "exposure_time_absolute", "gain", "white_balance_temperature",
    "focus_absolute", "brightness", "contrast", "saturation", "sharpness",
    "hue", "power_line_frequency", "backlight_compensation", "red_balance", "blue_balance",
)
PRESETS = {"call": "Normal call", "close": "Close-up", "standing": "Wide standing"}


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.data = {"version": 1, "settings": {}, "presets": {}}
        self.error = ""
        try:
            data = json.loads(self.path.read_text())
            if (not isinstance(data, dict) or data.get("version") != 1 or not isinstance(data.get("settings"), dict)
                    or not isinstance(data.get("presets"), dict)):
                raise ValueError("Unknown profile file format")
            self.data = data
        except FileNotFoundError:
            pass
        except (ValueError, OSError) as error:
            self.error = "Cannot read saved profiles: " + str(error)

    def save(self, data):
        if self.error:
            raise RuntimeError(self.error + "; existing file was preserved")
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix=".profiles-", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w") as stream:
                json.dump(data, stream, indent=2, sort_keys=True)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, self.path)
            self.data = data
        finally:
            if os.path.exists(name):
                os.unlink(name)

    def setting(self, name, value):
        updated = dict(self.data)
        updated["settings"] = {**updated["settings"], name: value}
        self.save(updated)


class Controller:
    def __init__(self, store, camera_factory=Camera):
        self.store = store
        self.camera_factory = camera_factory
        self.camera = None
        self.restore_error = ""
        self.last_awake = False

    def close(self):
        if self.camera:
            self.camera.close()
        self.camera = None

    def connect(self):
        if self.camera is None:
            self.camera = self.camera_factory()
            self.camera.privacy()
            self.last_awake = False

    def validate_settings(self, settings):
        if not isinstance(settings, dict) or set(settings) - set(IMAGE_CONTROLS + ("hdr", "trackingSpeed")):
            raise ValueError("Invalid saved image settings")
        controls = self.camera.controls()
        for key in IMAGE_CONTROLS:
            if key in settings and key in controls:
                Camera.validate(controls[key], settings[key])
        if "hdr" in settings and type(settings["hdr"]) is not bool:
            raise ValueError("Invalid saved HDR setting")
        if "trackingSpeed" in settings and (type(settings["trackingSpeed"]) is not int
                                            or settings["trackingSpeed"] not in (0, 2)):
            raise ValueError("Invalid saved tracking speed")

    def apply_settings(self, settings):
        self.validate_settings(settings)
        # Auto controls precede dependent manual controls; manual controls that
        # are inactive under the selected auto mode do not get written.
        for key in IMAGE_CONTROLS:
            if key in settings:
                control = self.camera.controls().get(key)
                if control and not control["inactive"]:
                    self.camera.set(control, settings[key])
        if "hdr" in settings:
            self.camera.hdr(settings["hdr"])
        if "trackingSpeed" in settings and self.camera.status()["trackingSpeedSupported"]:
            self.camera.tracking_speed(settings["trackingSpeed"])

    def snapshot(self):
        presets = [{"id": key, "label": label,
                    "saved": key in self.store.data["presets"]}
                   for key, label in PRESETS.items()]
        base = {"connected": False, "error": "", "controls": {}, "presets": presets,
                "profileError": self.store.error, "positionReadable": False,
                "awake": False, "voiceMask": None, "microphoneEnabled": None}
        try:
            self.connect()
            current = self.camera.status()
            # Restore adjustments on reconnect/wake, never wake or move the
            # camera just because the desktop shell starts.
            self.camera.privacy()
            if current["awake"] and not self.last_awake:
                self.last_awake = True
                try:
                    self.apply_settings(self.store.data["settings"])
                    self.restore_error = ""
                except (ValueError, RuntimeError) as error:
                    self.restore_error = "Cannot restore image settings: " + str(error)
            self.last_awake = current["awake"]
            current = self.camera.status()
            controls = self.camera.controls() if current["awake"] else {}
            base.update(current, connected=True, name=self.camera.name,
                        device=self.camera.path, controls=controls, settingsError=self.restore_error)
            if current["awake"]:
                try:
                    base["position"] = self.camera.position()
                    base["positionReadable"] = True
                except (OSError, ValueError, RuntimeError) as error:
                    base["positionError"] = str(error)
            return base
        except (OSError, ValueError, RuntimeError) as error:
            self.close()
            base["error"] = str(error)
            return base

    def action(self, request):
        operation = request.get("action")
        if operation == "status":
            return
        self.connect()
        if operation == "privacy":
            self.camera.privacy()
            return
        if operation == "wake":
            self.camera.wake()
            self.apply_settings(self.store.data["settings"])
            self.last_awake = True
            return
        if operation == "sleep":
            self.camera.sleep()
            self.last_awake = False
            return
        if not self.camera.status()["awake"]:
            raise RuntimeError("Wake the camera before adjusting it")
        if operation == "tracking":
            if type(request.get("value")) is not bool:
                raise ValueError("Tracking requires true or false")
            self.camera.tracking(request["value"])
        elif operation == "tracking-speed":
            self.camera.tracking_speed(request["value"])
            self.store.setting("trackingSpeed", request["value"])
        elif operation == "hdr":
            if type(request.get("value")) is not bool:
                raise ValueError("HDR requires true or false")
            self.camera.hdr(request["value"])
            self.store.setting("hdr", request["value"])
        elif operation == "center":
            self.camera.center()
        elif operation == "nudge":
            self.camera.nudge(request["direction"])
        elif operation == "set":
            key = request["control"]
            if key not in IMAGE_CONTROLS + ("zoom_absolute",):
                raise ValueError("This camera control is not editable")
            control = self.camera.controls()[key]
            if control["inactive"]:
                raise ValueError("Turn off the corresponding auto mode first")
            self.camera.set(control, request["value"])
            if key in IMAGE_CONTROLS:
                self.store.setting(key, request["value"])
        elif operation == "save-preset":
            key = request["preset"]
            if key not in PRESETS:
                raise ValueError("Unknown preset")
            if self.camera.status()["tracking"]:
                raise RuntimeError("Turn tracking off before saving a stationary preset")
            position = self.camera.settle()
            controls = self.camera.controls()
            settings = {key: controls[key]["value"] for key in IMAGE_CONTROLS
                        if key in controls and not controls[key]["inactive"]
                        and controls[key]["value"] is not None}
            status = self.camera.status()
            settings.update(hdr=status["hdr"])
            if status["trackingSpeedSupported"]:
                settings["trackingSpeed"] = status["trackingSpeed"]
            zoom = controls["zoom_absolute"]["value"]
            if zoom is None:
                raise RuntimeError("Camera did not provide a valid zoom position")
            preset = {"position": position, "zoom": zoom, "settings": settings}
            data = dict(self.store.data)
            data["presets"] = {**data["presets"], key: preset}
            self.store.save(data)
        elif operation == "recall-preset":
            preset = self.store.data["presets"].get(request["preset"])
            if not preset:
                raise RuntimeError("Save this preset's framing first")
            # Validate the entire stored preset before moving the camera.
            if (not isinstance(preset, dict) or set(preset) != {"position", "zoom", "settings"}
                    or not isinstance(preset["position"], dict)
                    or set(preset["position"]) != {"pan_absolute", "tilt_absolute"}):
                raise ValueError("Invalid saved preset")
            self.validate_settings(preset["settings"])
            controls = self.camera.controls()
            for key, value in {**preset["position"], "zoom_absolute": preset["zoom"]}.items():
                if key not in ("pan_absolute", "tilt_absolute", "zoom_absolute"):
                    raise ValueError("Invalid preset position")
                control = controls[key]
                if type(value) is not int or not control["minimum"] <= value <= control["maximum"]:
                    raise ValueError("Saved preset position is outside the camera's range")
            Camera.validate(controls["zoom_absolute"], preset["zoom"])
            self.camera.tracking(False)
            self.apply_settings(preset["settings"])
            self.camera.move(preset["position"])
            self.camera.set(controls["zoom_absolute"], preset["zoom"])
            data = dict(self.store.data)
            data["settings"] = dict(preset["settings"])
            self.store.save(data)
        else:
            raise ValueError("Unknown camera action")


def reply(controller, request=None):
    error = ""
    if request is not None:
        try:
            controller.action(request)
        except (OSError, ValueError, RuntimeError, KeyError, TypeError) as failure:
            error = str(failure)
    return {"id": request.get("id") if request else None,
            "ok": not error, "error": error, "state": controller.snapshot()}


def serve(controller):
    selector = selectors.DefaultSelector()
    selector.register(sys.stdin.fileno(), selectors.EVENT_READ)
    buffer = b""
    watching = False
    next_poll = 0
    try:
        while True:
            now = time.monotonic()
            if now >= next_poll:
                print(json.dumps(reply(controller)), flush=True)
                next_poll = now + (0.8 if watching else 5)
            for _, _ in selector.select(max(0, next_poll - time.monotonic())):
                chunk = os.read(sys.stdin.fileno(), 4096)
                if not chunk:
                    return
                buffer += chunk
                if len(buffer) > 16384:
                    raise ValueError("Camera request exceeded its size limit")
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    try:
                        request = json.loads(line)
                        if not isinstance(request, dict):
                            raise ValueError("Camera request must be an object")
                        if request.get("action") == "watch":
                            watching = request.get("value") is True
                            request["action"] = "status"
                        print(json.dumps(reply(controller, request)), flush=True)
                        next_poll = time.monotonic() + (0.8 if watching else 5)
                    except ValueError as error:
                        print(json.dumps({"id": None, "ok": False,
                                          "error": str(error)}), flush=True)
    finally:
        selector.close()


def terminate(_signum, _frame):
    raise SystemExit(0)


def main():
    parser = argparse.ArgumentParser(description="Control the OBSBOT Tiny 3 through Linux UVC")
    parser.add_argument("action", nargs="?", default="status",
                        choices=("status", "privacy", "wake", "sleep", "serve", "request"))
    parser.add_argument("json_request", nargs="?")
    parser.add_argument("--state-file", type=Path, default=Path(os.environ.get(
        "XDG_STATE_HOME", str(Path.home() / ".local/state"))) / "obsbot/profiles.json")
    args = parser.parse_args()
    controller = Controller(Store(args.state_file))
    runtime = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp"))
    with (runtime / ("obsbot-control-%d.lock" % os.getuid())).open("a") as lock:
        os.chmod(lock.name, 0o600)
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            parser.exit(1, "Camera helper is already running in Quickshell\n")
        signal.signal(signal.SIGTERM, terminate)
        try:
            if args.action == "serve":
                serve(controller)
            else:
                request = json.loads(args.json_request) if args.action == "request" else {"action": args.action}
                if not isinstance(request, dict):
                    parser.error("Camera request must be a JSON object")
                result = reply(controller, request)
                print(json.dumps(result))
                return 0 if result["ok"] and result["state"]["connected"] else 1
        finally:
            controller.close()


if __name__ == "__main__":
    sys.exit(main())

"""Protocol and persistence contracts; no hardware or vendor libraries required."""

import json
import os
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

from controller import Controller, Store, reply
from transport import Camera, decode_status, frame


def control(value, low=0, high=100, inactive=False):
    return {"id": 1, "name": "Test", "type": 1, "minimum": low,
            "maximum": high, "step": 1, "value": value,
            "inactive": inactive, "options": []}


class FakeCamera:
    name = "OBSBOT Tiny 3"
    path = "/dev/video0"

    def __init__(self):
        self.state = {"awake": True, "hdr": False, "tracking": False,
                      "voiceMask": 127, "microphoneEnabled": True,
                      "trackingSpeed": 0, "trackingSpeedSupported": False}
        self.values = {"zoom_absolute": 0, "white_balance_automatic": 1,
                       "white_balance_temperature": 4500, "brightness": 0}
        self.pose = {"pan_absolute": 10800, "tilt_absolute": -7200}
        self.writes = []
        self.closed = False
        self.position_error = False

    def close(self):
        self.closed = True

    def privacy(self):
        self.state.update(voiceMask=0, microphoneEnabled=False)

    def status(self):
        return dict(self.state)

    def controls(self):
        descriptors = {key: {**control(value, high=10000 if "temperature" in key else 100,
                               inactive=key == "white_balance_temperature" and
                               self.values["white_balance_automatic"] == 1), "name": key}
                for key, value in self.values.items()}
        descriptors.update(pan_absolute=control(self.pose["pan_absolute"], -468000, 468000),
                           tilt_absolute=control(self.pose["tilt_absolute"], -324000, 324000))
        return descriptors

    def set(self, descriptor, value):
        Camera.validate(descriptor, value)
        self.writes.append((descriptor["name"], value))
        self.values[descriptor["name"]] = value

    def hdr(self, value):
        self.writes.append(("hdr", value))
        self.state["hdr"] = value

    def position(self):
        if self.position_error:
            raise RuntimeError("No position reply")
        return dict(self.pose)

    def settle(self):
        return self.position()

    def tracking(self, value):
        self.writes.append(("tracking", value))
        self.state["tracking"] = value

    def move(self, pose):
        self.writes.append(("move", pose))
        self.pose = dict(pose)


class ProtocolTests(unittest.TestCase):
    def test_vendor_frame_matches_captured_obsbot_center_packet(self):
        # Primary reference: lxman/obsbot-mcp's captured Standard packet.
        packet = frame(0x0cc4, 4, b"\0", sequence=0x14)
        self.assertEqual(packet[:17].hex(), "aa2514000c00eae10a04c40c0100e63f00")
        self.assertEqual(len(packet), 60)
        self.assertEqual(packet[17:], bytes(43))

    def test_payload_size_is_bounded(self):
        with self.assertRaises(ValueError):
            frame(1, 4, bytes(45))

    def test_privacy_disables_all_voice_commands_and_usb_audio(self):
        camera = Camera.__new__(Camera)
        status = {"voiceMask": 127, "microphoneEnabled": True, "microphoneInSleep": True}
        writes = []

        def tag(code, payload):
            writes.append((code, payload))
            if code == 0x15:
                status["voiceMask"] &= ~(1 << payload[0])
            elif code == 0x13:
                status["microphoneInSleep"] = False
            elif code == 0x1c:
                status["microphoneEnabled"] = False

        camera.status = lambda: dict(status)
        camera.tag = tag
        with patch("transport.time.sleep"):
            camera.privacy()
            camera.privacy()  # Already disabled: no repeated USB reset.
        self.assertEqual(writes, [(0x15, bytes((bit, 0))) for bit in range(7)] +
                         [(0x13, b"\0"), (0x1c, b"\0")])

    def test_unknown_status_is_rejected(self):
        with self.assertRaises(ValueError):
            decode_status(bytes(60))

    def test_motor_pose_uses_signed_tenths_and_ignores_euler_orientation(self):
        camera = Camera.__new__(Camera)
        camera.read_command = lambda *_: struct.pack("<12h", 0, 100, 900, 0, -25,
                                                    123, 0, 0, 0, 0, 0, 0)
        self.assertEqual(camera.position(), {"pan_absolute": 44280, "tilt_absolute": 9000})

    def test_arrow_movement_is_bounded_absolute_position(self):
        camera = Camera.__new__(Camera)
        camera.tracking = lambda _: None
        camera.settle = lambda: {"pan_absolute": 467000, "tilt_absolute": 0}
        moved = []
        camera.move = moved.append
        camera.nudge("left")
        self.assertEqual(moved, [{"pan_absolute": 468000, "tilt_absolute": 0}])
        with self.assertRaises(ValueError):
            camera.nudge("arbitrary")


class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "profiles.json"
        self.store = Store(self.path)
        self.camera = FakeCamera()
        self.controller = Controller(self.store, lambda: self.camera)

    def tearDown(self):
        self.controller.close()
        self.directory.cleanup()

    def test_corrupt_and_non_object_files_are_preserved(self):
        for contents in ("[1, 2]", "{broken", '{"version":2}'):
            self.path.write_text(contents)
            store = Store(self.path)
            self.assertTrue(store.error)
            with self.assertRaises(RuntimeError):
                store.setting("hdr", True)
            self.assertEqual(self.path.read_text(), contents)

    def test_atomic_private_storage_and_reload(self):
        self.store.setting("hdr", True)
        self.assertEqual(os.stat(self.path).st_mode & 0o777, 0o600)
        self.assertEqual(Store(self.path).data["settings"], {"hdr": True})
        self.assertEqual(list(self.path.parent.glob(".profiles-*")), [])

    def test_manual_controls_follow_auto_controls_when_restoring(self):
        self.controller.connect()
        self.controller.apply_settings({"white_balance_temperature": 5200,
                                        "white_balance_automatic": 0})
        self.assertEqual(self.camera.writes, [("white_balance_automatic", 0),
                                             ("white_balance_temperature", 5200)])
        self.camera.writes.clear()
        self.controller.apply_settings({"white_balance_temperature": 5200,
                                        "white_balance_automatic": 1})
        self.assertEqual(self.camera.writes, [("white_balance_automatic", 1)])

    def test_unconfirmed_control_is_not_persisted(self):
        self.controller.connect()
        self.camera.set = lambda *_: (_ for _ in ()).throw(RuntimeError("Rejected"))
        result = reply(self.controller, {"action": "set", "control": "brightness", "value": 20})
        self.assertFalse(result["ok"])
        self.assertFalse(self.path.exists())

    def test_preset_roundtrip_uses_live_pose_and_saved_image_profile(self):
        self.controller.action({"action": "save-preset", "preset": "call"})
        saved = json.loads(self.path.read_text())["presets"]["call"]
        self.assertEqual(saved["position"], self.camera.pose)
        self.assertNotIn("trackingSpeed", saved["settings"])
        self.camera.pose = {"pan_absolute": 0, "tilt_absolute": 0}
        self.camera.values["brightness"] = 30
        self.controller.action({"action": "recall-preset", "preset": "call"})
        self.assertEqual(self.camera.pose, saved["position"])
        self.assertEqual(self.camera.values["brightness"], 0)
        self.assertEqual(self.store.data["settings"], saved["settings"])

    def test_invalid_preset_is_rejected_before_hardware_changes(self):
        self.store.data["presets"]["call"] = {
            "position": {"pan_absolute": 0, "tilt_absolute": 0},
            "zoom": 10, "settings": {"hdr": "true"}}
        with self.assertRaises(ValueError):
            self.controller.action({"action": "recall-preset", "preset": "call"})
        self.assertEqual(self.camera.writes, [])

    def test_shell_start_does_not_wake_or_move_sleeping_camera(self):
        self.store.setting("brightness", 20)
        self.camera.state["awake"] = False
        state = self.controller.snapshot()
        self.assertTrue(state["connected"])
        self.assertFalse(state["awake"])
        self.assertEqual(state["controls"], {})
        self.assertEqual(self.camera.writes, [])
        self.assertEqual(state["voiceMask"], 0)
        self.assertFalse(state["microphoneEnabled"])

    def test_bad_profile_and_missing_position_do_not_hide_connected_camera(self):
        self.store.data["settings"] = {"brightness": "invalid"}
        self.camera.position_error = True
        first = self.controller.snapshot()
        self.assertTrue(first["connected"])
        self.assertFalse(first["positionReadable"])
        self.assertIn("Cannot restore", first["settingsError"])
        self.assertEqual(self.controller.snapshot()["settingsError"], first["settingsError"])
        self.assertFalse(self.camera.closed)


if __name__ == "__main__":
    unittest.main()

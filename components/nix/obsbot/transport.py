"""Small Linux UVC transport for the OBSBOT Tiny 3 (3564:ff02).

Wire framing follows lxman/obsbot-mcp (MIT); see NOTICE.
Voice/audio tags were checked against OBSBOT libdev 1.0.2 disassembly.
No SDK, streaming, kernel driver detachment, or arbitrary command interface.
"""

import ctypes
import errno
import fcntl
import os
from pathlib import Path
import struct
import time


class XuQuery(ctypes.Structure):
    _fields_ = [("unit", ctypes.c_uint8), ("selector", ctypes.c_uint8),
                ("query", ctypes.c_uint8), ("size", ctypes.c_uint16),
                ("data", ctypes.c_void_p)]


def crc16(data):
    crc = 0xffff
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ (0xa001 if crc & 1 else 0)
    return crc ^ 0xffff


def frame(command, receiver, payload=b"", sequence=1, flags=0x25):
    if len(payload) > 44:
        raise ValueError("Vendor payload too long")
    data = bytearray(60)
    struct.pack_into("<BBHHHBBH", data, 0, 0xaa, flags, sequence, 12, 0,
                     0x0a, receiver, command)
    struct.pack_into("<H", data, 6, crc16(data[:12]))
    if payload:
        struct.pack_into("<HH", data, 12, len(payload), 0)
        data[16:16 + len(payload)] = payload
        struct.pack_into("<H", data, 14, crc16(data[12:16 + len(payload)]))
    return bytes(data)


def decode_status(data):
    if len(data) != 60 or data[9] not in (1, 3, 4):
        raise ValueError("Invalid Tiny 3 status block")
    return {
        "awake": data[9] == 1, "runState": data[9],
        "hdr": bool(data[6]), "hdrSupported": bool(data[30]),
        "tracking": data[24] != 0, "trackingMode": data[24],
        "trackingSpeed": data[36], "trackingSpeedSupported": False, "voiceMask": data[21],
        "microphoneEnabled": bool(data[34] & 0x10),
        "microphoneInSleep": bool(data[16]),
        "zoomPercent": struct.unpack_from("<H", data, 4)[0],
    }


class Camera:
    def __init__(self, path=None):
        self.fd = None
        self.sequence = int(time.monotonic() * 1000) % 65535
        for entry in sorted(Path("/sys/class/video4linux").glob("video*")):
            device = next((p for p in entry.resolve().parents
                           if (p / "idVendor").exists()), None)
            if not device or (device / "idVendor").read_text().strip() != "3564":
                continue
            if (device / "idProduct").read_text().strip() != "ff02":
                continue
            candidate = "/dev/" + entry.name
            if path is not None and candidate != path:
                continue
            descriptor = (device / "descriptors").read_bytes()
            guid = bytes.fromhex("91721e9a436883466d9239bc7906ee49")
            if guid not in descriptor:
                raise ValueError("Tiny 3 vendor extension GUID does not match")
            fd = os.open(candidate, os.O_RDWR | os.O_NONBLOCK)
            caps = bytearray(104)
            fcntl.ioctl(fd, 0x80685600, caps)
            if not struct.unpack_from("<I", caps, 88)[0] & 1:
                os.close(fd)
                continue
            self.fd, self.path = fd, candidate
            self.name = (entry / "name").read_text().strip()
            try:
                self.status()
            except Exception:
                self.close()
                raise
            return
        raise FileNotFoundError("OBSBOT Tiny 3 is disconnected")

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
        self.fd = None

    def xu(self, selector, payload=None):
        data = (ctypes.c_uint8 * 60)()
        if payload is not None:
            if len(payload) > 60:
                raise ValueError("UVC payload too long")
            data[:len(payload)] = payload
        query = XuQuery(2, selector, 0x81 if payload is None else 1,
                        60, ctypes.addressof(data))
        fcntl.ioctl(self.fd, 0xc0107521, bytes(query))
        return bytes(data)

    def status(self):
        return decode_status(self.xu(6))

    def tag(self, tag, payload):
        self.xu(6, bytes((tag, len(payload))) + payload)

    def command(self, command, receiver, payload=b""):
        self.sequence = (self.sequence + 1) % 65536
        self.xu(2, frame(command, receiver, payload, self.sequence))

    def read_command(self, command, receiver):
        self.sequence = (self.sequence + 1) % 65536
        self.xu(2, frame(command, receiver, sequence=self.sequence, flags=1))
        for _ in range(5):
            time.sleep(0.05)
            data = self.xu(2)
            if data[0] != 0xaa:
                continue
            sequence = struct.unpack_from("<H", data, 2)[0]
            received_command = struct.unpack_from("<H", data, 10)[0]
            if sequence != self.sequence or received_command != command:
                continue
            header = bytearray(data[:12])
            header[6:8] = bytes(2)
            if struct.unpack_from("<H", data, 6)[0] != crc16(header):
                raise ValueError("Invalid vendor reply checksum")
            size = struct.unpack_from("<H", data, 12)[0]
            if size > 44:
                raise ValueError("Invalid vendor reply length")
            segment = bytearray(data[12:16 + size])
            segment[2:4] = bytes(2)
            if struct.unpack_from("<H", data, 14)[0] != crc16(segment):
                raise ValueError("Invalid vendor payload checksum")
            return data[16:16 + size]
        raise RuntimeError("Camera did not return vendor position data")

    def wait(self, field, expected, timeout=2):
        deadline = time.monotonic() + timeout
        while True:
            current = self.status()
            if current[field] == expected:
                return current
            if time.monotonic() >= deadline:
                raise RuntimeError("Camera did not confirm %s = %s" % (field, expected))
            time.sleep(0.08)

    def privacy(self):
        current = self.status()
        if current["voiceMask"]:
            for bit in range(7):
                self.tag(0x15, bytes((bit, 0)))
                time.sleep(0.04)
            self.wait("voiceMask", 0)
        if current["microphoneInSleep"]:
            self.tag(0x13, b"\0")
            self.wait("microphoneInSleep", False)
        if current["microphoneEnabled"]:
            self.tag(0x1c, b"\0")
            self.wait("microphoneEnabled", False)
        return self.status()

    def wake(self):
        self.command(0xa0c2, 2, struct.pack("<I", 0))
        self.wait("awake", True, 5)
        time.sleep(0.3)
        self.privacy()
        # Run state changes before the gimbal finishes leaving its sleep pose.
        if not self.status()["tracking"]:
            self.settle()

    def sleep(self):
        self.command(0xa0c2, 2, struct.pack("<I", 1))
        self.wait("awake", False, 5)

    def controls(self):
        result = {}
        previous = 0
        while True:
            data = bytearray(struct.pack("<II32siiiiI2I", previous | 0x80000000,
                                        0, b"", 0, 0, 0, 0, 0, 0, 0))
            try:
                fcntl.ioctl(self.fd, 0xc0445624, data)
            except OSError as error:
                if error.errno == errno.EINVAL:
                    break
                raise
            cid, kind, name, low, high, step, default, flags, _, _ = struct.unpack(
                "<II32siiiiI2I", data)
            previous = cid
            if flags & 1 or kind not in (1, 2, 3):
                continue
            name = name.split(b"\0", 1)[0].decode("utf-8")
            key = name.lower().replace(" ", "_").replace(",", "")
            value = self.get(cid)
            options = []
            if kind == 3:
                for index in range(low, high + 1):
                    menu = bytearray(struct.pack("<II32sI", cid, index, b"", 0))
                    try:
                        fcntl.ioctl(self.fd, 0xc02c5625, menu)
                        label = bytes(menu[8:40]).split(b"\0", 1)[0].decode()
                        options.append({"value": index, "label": label})
                    except OSError as error:
                        if error.errno != errno.EINVAL:
                            raise
            valid = low <= value <= high and (kind != 3 or any(
                item["value"] == value for item in options))
            result[key] = {"id": cid, "name": name, "type": kind,
                           "minimum": low, "maximum": high, "step": max(1, step),
                           "default": default, "value": value if valid else None,
                           "inactive": bool(flags & 0x10), "options": options}
        return result

    def get(self, cid):
        data = bytearray(struct.pack("<Ii", cid, 0))
        fcntl.ioctl(self.fd, 0xc008561b, data)
        return struct.unpack_from("<i", data, 4)[0]

    @staticmethod
    def validate(control, value):
        if type(value) is not int:
            raise ValueError("Control value must be an integer")
        if not control["minimum"] <= value <= control["maximum"]:
            raise ValueError("Control value is outside the camera's range")
        if (value - control["minimum"]) % control["step"]:
            raise ValueError("Control value is not on the camera's step")
        if control["type"] == 3 and value not in [o["value"] for o in control["options"]]:
            raise ValueError("Invalid camera menu option")

    def set(self, control, value):
        self.validate(control, value)
        fcntl.ioctl(self.fd, 0xc008561c, struct.pack("<Ii", control["id"], value))
        if self.get(control["id"]) != value:
            raise RuntimeError("Camera did not confirm " + control["name"])

    def tracking(self, enabled):
        self.tag(0x16, bytes((2 if enabled else 0, 0)))
        self.wait("tracking", enabled)

    def tracking_speed(self, value):
        # Neither Tiny 2's 0x0cc4 nor the SDK's 0x0944 confirms a speed change
        # on PW106, even with an active stream. 0x0cc4 can change its AI mode.
        # Do not echo a requested value as though the hardware accepted it.
        raise RuntimeError("Tracking-speed adjustment is not verified for this Tiny 3 firmware")

    def hdr(self, enabled):
        self.tag(1, bytes((int(enabled),)))
        self.wait("hdr", enabled)

    def center(self):
        self.tracking(False)
        self.move({"pan_absolute": 0, "tilt_absolute": 0})

    def nudge(self, direction):
        # Absolute three-degree steps cannot leave a velocity command running.
        axes = {"left": (10800, 0), "right": (-10800, 0),
                "up": (0, 10800), "down": (0, -10800)}
        if direction not in axes:
            raise ValueError("Invalid PTZ direction")
        self.tracking(False)
        pose = self.settle()
        pan, tilt = axes[direction]
        self.move({"pan_absolute": max(-468000, min(468000, pose["pan_absolute"] + pan)),
                   "tilt_absolute": max(-324000, min(324000, pose["tilt_absolute"] + tilt))})

    def gimbal(self):
        # AI_GET_GIM_STATE: nine int16 values in tenths of a degree:
        # euler roll/pitch/yaw, motor roll/pitch/yaw, velocities.
        # Checked against libdev 1.0.3's reply decoder at 0x4d500. Motor pose
        # is the reproducible framing; euler angles include device orientation.
        data = self.read_command(0x6604, 4)
        if len(data) != 24:
            raise ValueError("Unknown Tiny 3 gimbal-status layout")
        pitch, yaw = struct.unpack_from("<hh", data, 8)
        pan, tilt = yaw * 360, -pitch * 360
        if not (-468000 <= pan <= 468000 and -324000 <= tilt <= 324000):
            raise ValueError("Camera position readback is outside its range")
        velocity = struct.unpack_from("<hhh", data, 12)
        return {"pan_absolute": pan, "tilt_absolute": tilt}, max(map(abs, velocity)) < 5

    def position(self):
        return self.gimbal()[0]

    def settle(self, target=None, timeout=8):
        deadline = time.monotonic() + timeout
        stable = 0
        while time.monotonic() < deadline:
            actual, stopped = self.gimbal()
            reached = target is None or all(abs(actual[key] - target[key]) <= 1800
                                           for key in actual)
            stable = stable + 1 if stopped and reached else 0
            if stable >= 3:
                return actual
            time.sleep(0.15)
        raise RuntimeError("Camera did not settle at the requested position")

    def move(self, position):
        pan, tilt = position["pan_absolute"], position["tilt_absolute"]
        if not (-468000 <= pan <= 468000 and -324000 <= tilt <= 324000):
            raise ValueError("Preset position is outside the camera's range")
        self.command(0x6444, 4, struct.pack("<fff", -1000, -tilt / 3600, pan / 3600))
        self.settle(position)

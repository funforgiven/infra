"""Parse the built Duo profiles with ALSA, without opening audio hardware."""

import ctypes
import os
from pathlib import Path
import sys
import tempfile


ucm_root = Path(sys.argv[1]) / "share/alsa/ucm2"
alsa = ctypes.CDLL(sys.argv[2])
pointer = ctypes.c_void_p
string = ctypes.c_char_p
alsa.snd_use_case_mgr_open.argtypes = [ctypes.POINTER(pointer), string]
alsa.snd_use_case_mgr_close.argtypes = [pointer]
alsa.snd_use_case_set.argtypes = [pointer, string, string]
alsa.snd_use_case_get.argtypes = [pointer, string, ctypes.POINTER(pointer)]
libc = ctypes.CDLL(None)
libc.free.argtypes = [pointer]


def get(manager, key):
    value = pointer()
    result = alsa.snd_use_case_get(manager, key.encode(), ctypes.byref(value))
    assert result == 0, (key, result)
    try:
        return ctypes.string_at(value).decode()
    finally:
        libc.free(value)


with tempfile.TemporaryDirectory(prefix="duo-ucm-check-") as directory:
    root = Path(directory)
    os.environ["ALSA_CONFIG_UCM2"] = directory
    (root / "common/pcm").mkdir(parents=True)
    # Only substitute the card identity, which normally comes from the kernel.
    split = (ucm_root / "common/pcm/split.conf").read_text()
    (root / "common/pcm/split.conf").write_text(split.replace("${CardId}", "Duo"))
    profile = (ucm_root / "USB-Audio/RODE/RODECaster-Duo-Expanded.conf").read_text()
    profile = profile.replace("${CardId}", "Duo")
    (root / "ucm.conf").write_text(
        'Syntax 4\nUseCasePath.test { Directory "." File "test.conf" }\n'
    )
    for product, capture_channels in [("0079", 2), ("0073", 16), ("0095", 20)]:
        mode = (ucm_root / f"USB-Audio/conf.d/19f7-{product}.conf").read_text()
        (root / "test.conf").write_text(
            "Syntax 8\nDefine.SplitPCMPeriodTime 10000\n" + mode + profile
        )
        manager = pointer()
        result = alsa.snd_use_case_mgr_open(
            ctypes.byref(manager), b"<<<SplitPCM=1>>>strict:duo-test"
        )
        assert result == 0, (product, result)
        try:
            assert alsa.snd_use_case_set(manager, b"_verb", b"HiFi") == 0
            for device, left in [("Speaker", 0), ("Line1", 2), ("Line2", 4)]:
                assert get(manager, f"PlaybackPCM/{device}") == "hw:Duo,1"
                assert get(manager, f"PlaybackChannels/{device}") == "10"
                assert get(manager, f"PlaybackChannel0/{device}") == str(left)
                assert get(manager, f"PlaybackChannel1/{device}") == str(left + 1)
                assert get(manager, f"PlaybackChannelPos0/{device}") == "FL"
                assert get(manager, f"PlaybackChannelPos1/{device}") == "FR"
            assert get(manager, "PlaybackPCM/Line3") == "hw:Duo,0"
            assert get(manager, "PlaybackChannels/Line3") == "2"
            assert get(manager, "CapturePCM/Mic") == "hw:Duo,0"
            assert get(manager, "CaptureChannels/Mic") == "2"
            assert get(manager, "CapturePCM/Line4") == "hw:Duo,1"
            assert get(manager, "CaptureChannels/Line4") == str(capture_channels)
        finally:
            alsa.snd_use_case_mgr_close(manager)
        print(f"PASS {product}: independent System/Game/Music pairs, Chat PCM, {capture_channels}-channel capture")

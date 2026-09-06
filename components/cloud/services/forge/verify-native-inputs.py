#!/usr/bin/env python3
"""Verify pinned native installation media and Apple's recovery signature."""

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys


def main():
    if sys.flags.optimize:
        raise SystemExit("Apple's verifier requires Python assertions; do not use -O.")
    manifest = json.loads(Path(__file__).with_name("native-inputs.json").read_text())
    parser = argparse.ArgumentParser(description=__doc__)
    for name in manifest:
        parser.add_argument("--" + name.replace("_", "-"), type=Path, required=True)
    args = parser.parse_args()
    for name, expected in manifest.items():
        with getattr(args, name).open("rb") as source:
            actual = hashlib.file_digest(source, "sha256").hexdigest()
        if actual != expected["sha256"]:
            raise SystemExit(f"{name}: checksum mismatch; input rejected")
        print(f"{name}: SHA256 verified", flush=True)
    spec = importlib.util.spec_from_file_location("apple_recovery_verifier", args.apple_verifier)
    verifier = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(verifier)
    count = 0
    with args.macos_recovery.open("rb") as image:
        # Exhaust the upstream generator: its RSA verification occurs after
        # the final chunk. Partial iteration would not authenticate the image.
        for size, expected in verifier.verify_chunklist(args.macos_chunklist):
            data = image.read(size)
            if len(data) != size or hashlib.sha256(data).digest() != expected:
                raise SystemExit("macOS recovery chunk rejected")
            count += 1
        if image.read(1):
            raise SystemExit("Unexpected bytes after macOS recovery image")
    print(f"Apple RSA signature and all {count} recovery chunks verified.")
    print("Installation inputs verified; guest execution requires separate qualification.")


if __name__ == "__main__":
    main()

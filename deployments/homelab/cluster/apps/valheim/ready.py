#!/usr/bin/python3
"""Require a responding Valheim 1.0 server, or a verified isolated restore."""
import os
from pathlib import Path
import sys

import a2s

if os.environ["POD_NAMESPACE"] != "games":
    sys.exit(0 if Path("/tmp/restore-ready").is_file() else 1)

try:
    info = a2s.info(("127.0.0.1", 2457), timeout=2)
    if not info.version.startswith("1.0."):
        raise ValueError(f"Expected Valheim 1.0, server reports {info.version!r}")
except Exception as error:
    print(f"Valheim is not ready: {error}", file=sys.stderr)
    sys.exit(1)

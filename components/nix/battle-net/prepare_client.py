"""Merge declared Battle.net browser settings into its private runtime config."""

import json
import ntpath
import os
from pathlib import Path
import sys
import tempfile


def client_running(prefix, proc=Path("/proc")):
    prefix = prefix.resolve()
    for process in proc.iterdir():
        if not process.name.isdecimal():
            continue
        try:
            if process.stat().st_uid != os.getuid():
                continue
            executable = (process / "cmdline").read_bytes().split(b"\0", 1)[0].decode(errors="replace")
            if ntpath.basename(executable).casefold() not in {
                "battle.net.exe", "battle.net launcher.exe", "blizzardbrowser.exe",
            }:
                continue
            environment = dict(
                entry.split(b"=", 1)
                for entry in (process / "environ").read_bytes().split(b"\0")
                if b"=" in entry
            )
            # Proton exposes WINEPREFIX through its pfx/ alias, while UMU
            # keeps the declared prefix in STEAM_COMPAT_DATA_PATH.
            if any(
                value and Path(os.fsdecode(value)).resolve() == prefix
                for value in (
                    environment.get(b"WINEPREFIX"),
                    environment.get(b"STEAM_COMPAT_DATA_PATH"),
                )
            ):
                return True
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue
    return False


def prepare_client(prefix, settings):
    path = prefix / "drive_c/users/steamuser/AppData/Roaming/Battle.net/Battle.net.config"
    original = path.read_bytes() if path.exists() else None
    document = json.loads(original) if original is not None else {}
    client = document.setdefault("Client", {})
    if all(client.get(key) == value for key, value in settings.items()):
        return False
    if client_running(prefix):
        raise RuntimeError("Close Battle.net before changing its declared browser settings")
    client.update(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as output:
            temporary = Path(output.name)
            json.dump(document, output, indent=4, ensure_ascii=False)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        if (path.read_bytes() if path.exists() else None) != original:
            raise RuntimeError("Battle.net configuration changed while applying settings; retry")
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return True


if __name__ == "__main__":
    try:
        changed = prepare_client(Path(sys.argv[1]), json.loads(Path(sys.argv[2]).read_bytes()))
    except (OSError, ValueError, AttributeError, TypeError, RuntimeError):
        print("battlenet: could not apply browser settings; close Battle.net and check its config file.",
              file=sys.stderr)
        sys.exit(1)
    if changed:
        print("battlenet: applied declared browser settings")

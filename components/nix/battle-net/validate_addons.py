"""Validate the built addon bundle against Forever TOCs and required dependencies."""

import base64
import json
from pathlib import Path
import re
import sys


def validate(lock, bundle):
    assert lock["schemaVersion"] == 1 and lock["flavour"] == "forever_classic"
    folders = [folder for addon in lock["addons"].values() for folder in addon["folders"]]
    assert len(folders) == len(set(folders)), "Addon archives claim duplicate folders"
    assert sorted(folders) == sorted(entry.name for entry in bundle.iterdir())
    for addon in lock["addons"].values():
        assert addon["version"] and addon["url"].startswith("https://")
        assert addon["hash"].startswith("sha256-")
        assert len(base64.b64decode(addon["hash"].removeprefix("sha256-"), validate=True)) == 32
    for folder in folders:
        assert re.fullmatch(r"[A-Za-z0-9_!-]+", folder), f"Invalid addon folder: {folder}"
        tocs = list((bundle / folder).glob("*.toc"))
        compatible = [
            toc for toc in tocs
            if re.search(r"^## Interface[^:]*:.*\b16001\b", toc.read_text(encoding="utf-8-sig"), re.M)
        ]
        assert compatible, f"{folder} has no Forever-compatible TOC"
        for toc in compatible:
            for group in re.findall(
                r"^## (?:Dependencies|RequiredDeps):[ \t]*(.*)$",
                toc.read_text(encoding="utf-8-sig"), re.M | re.I,
            ):
                for dependency in re.split(r"[,\s]+", group.strip()):
                    assert not dependency or dependency.startswith("Blizzard_") or dependency in folders, (
                        f"{folder} requires missing addon {dependency}"
                    )


if __name__ == "__main__":
    validate(json.loads(Path(sys.argv[1]).read_text()), Path(sys.argv[2]))

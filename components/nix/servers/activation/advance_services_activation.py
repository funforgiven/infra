#!/usr/bin/env python3
"""Enable one declaratively gated service activation stage."""

from __future__ import annotations

import argparse
from pathlib import Path


UNDERCLOUD_WAVES = Path("deployments/homelab/cloud/undercloud/20-gitops/waves.yaml")
SERVICES_WAVES = Path("deployments/homelab/cloud/services/waves.yaml")
STAGES = {
    "foundation": ((UNDERCLOUD_WAVES, "wave81-services-foundation"),),
    "cluster": ((UNDERCLOUD_WAVES, "wave82-services-cluster"),),
    "hosts": (
        (UNDERCLOUD_WAVES, "wave83-services-hosts"),
        (
            Path("deployments/homelab/cloud/undercloud/83-services-hosts/tofu.yaml"),
            "services-hosts",
        ),
    ),
    "mail": (
        (UNDERCLOUD_WAVES, "wave84-mail-edge"),
        (
            Path("deployments/homelab/cloud/undercloud/84-mail-edge/tofu.yaml"),
            "mail-edge",
        ),
    ),
    "mail-aws": (
        (
            Path("deployments/homelab/cloud/undercloud/84-mail-aws/tofu.yaml"),
            "mail-aws",
        ),
    ),
    "dns": (
        (UNDERCLOUD_WAVES, "wave85-service-dns"),
        (
            Path("deployments/homelab/cloud/undercloud/85-service-dns/tofu.yaml"),
            "service-dns",
        ),
    ),
    "observability": ((SERVICES_WAVES, "services-observability"),),
    "backup-controller": ((SERVICES_WAVES, "services-backup-controller"),),
    "backup-policy": ((SERVICES_WAVES, "services-backup-policy"),),
    "media": ((SERVICES_WAVES, "services-media"),),
    "home-automation": ((SERVICES_WAVES, "services-home-automation"),),
    "synthetic-monitoring": ((SERVICES_WAVES, "services-synthetic-monitoring"),),
}


def enable_resource(text: str, path: Path, resource: str) -> str:
    documents = text.split("\n---\n")
    matches = [
        index
        for index, document in enumerate(documents)
        if f"\n  name: {resource}\n" in "\n" + document
    ]
    if len(matches) != 1:
        raise ValueError(
            f"{path}: expected one document named {resource}, found {len(matches)}"
        )
    index = matches[0]
    suspended = "\n  suspend: true\n"
    active = "\n  suspend: false\n"
    candidate = "\n" + documents[index]
    if suspended not in candidate:
        if active in candidate:
            raise ValueError(f"{path}: {resource} is already active")
        raise ValueError(f"{path}: {resource} has no explicit suspension gate")
    documents[index] = documents[index].replace(suspended, active, 1)
    return "\n---\n".join(documents)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true")
    parser.add_argument("repository_root", nargs="?")
    parser.add_argument("stage", nargs="?", choices=sorted(STAGES))
    arguments = parser.parse_args()
    if arguments.list:
        print(" ".join(STAGES))
        return 0
    if not arguments.repository_root or not arguments.stage:
        parser.error("repository_root and stage are required")

    root = Path(arguments.repository_root)
    changes: list[tuple[Path, str]] = []
    try:
        for relative_path, resource in STAGES[arguments.stage]:
            path = root / relative_path
            changes.append(
                (
                    path,
                    enable_resource(path.read_text(encoding="utf-8"), path, resource),
                )
            )
    except (OSError, ValueError) as error:
        parser.exit(1, f"advance-services-activation: {error}\n")

    for path, text in changes:
        path.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Validate declarative ownership and documented manual exceptions."""

from __future__ import annotations

import pathlib
import sys
from collections.abc import Mapping, Sequence

import yaml


REQUIRED_EXCEPTION_FIELDS = {
    "id",
    "resource",
    "owner",
    "rationale",
    "procedure",
    "secret_handling",
    "backup",
    "drift_probe",
    "review_interval",
    "exit_criterion",
}

ALLOWED_DECLARATIVE_OWNERS = {
    "flux",
    "nixos",
    "opentofu",
    "pinned-api-reconciler",
    "sops",
}


def load_mapping(path: pathlib.Path) -> Mapping[str, object]:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(document, Mapping):
        raise ValueError(f"{path}: expected a mapping")
    return document


def require_nonempty_string(value: object, context: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{context}: expected a non-empty string")


def validate_ownership(path: pathlib.Path) -> None:
    document = load_mapping(path)
    resources = document.get("resources")
    if not isinstance(resources, Sequence) or isinstance(resources, (str, bytes)):
        raise ValueError(f"{path}: resources must be a list")

    seen: set[str] = set()
    for index, entry in enumerate(resources):
        context = f"{path}: resources[{index}]"
        if not isinstance(entry, Mapping):
            raise ValueError(f"{context}: expected a mapping")
        resource = entry.get("resource")
        owner = entry.get("owner")
        require_nonempty_string(resource, f"{context}.resource")
        if resource in seen:
            raise ValueError(f"{context}: duplicate resource {resource!r}")
        seen.add(resource)
        if owner not in ALLOWED_DECLARATIVE_OWNERS:
            raise ValueError(f"{context}: unsupported owner {owner!r}")
        require_nonempty_string(entry.get("state"), f"{context}.state")


def validate_exceptions(path: pathlib.Path) -> None:
    document = load_mapping(path)
    exceptions = document.get("exceptions")
    if not isinstance(exceptions, Sequence) or isinstance(exceptions, (str, bytes)):
        raise ValueError(f"{path}: exceptions must be a list")

    seen: set[str] = set()
    for index, entry in enumerate(exceptions):
        context = f"{path}: exceptions[{index}]"
        if not isinstance(entry, Mapping):
            raise ValueError(f"{context}: expected a mapping")
        missing = REQUIRED_EXCEPTION_FIELDS - set(entry)
        unknown = set(entry) - REQUIRED_EXCEPTION_FIELDS
        if missing or unknown:
            raise ValueError(
                f"{context}: missing={sorted(missing)} unknown={sorted(unknown)}"
            )
        for field in sorted(REQUIRED_EXCEPTION_FIELDS):
            require_nonempty_string(entry[field], f"{context}.{field}")
        exception_id = entry["id"]
        if exception_id in seen:
            raise ValueError(f"{context}: duplicate id {exception_id!r}")
        seen.add(exception_id)


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        raise SystemExit(
            "usage: validate_management_policy.py OWNERSHIP_YAML EXCEPTIONS_YAML"
        )
    validate_ownership(pathlib.Path(argv[1]))
    validate_exceptions(pathlib.Path(argv[2]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

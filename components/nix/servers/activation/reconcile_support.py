"""Validation and JSON-over-HTTPS helpers shared by the provider reconcilers."""

from __future__ import annotations

import json
import urllib.error
import urllib.request


def require_mapping(value: object, label: str, error: type[Exception]) -> dict:
    if not isinstance(value, dict):
        raise error(f"{label} must be a mapping")
    return value


def require_string(value: object, label: str, error: type[Exception]) -> str:
    if not isinstance(value, str) or not value:
        raise error(f"{label} must be a non-empty string")
    return value


def request_json(
    url: str,
    *,
    method: str,
    headers: dict[str, str],
    payload: dict | None,
    error: type[Exception],
    rejected: str,
    failed: str,
    allow_empty: bool = False,
) -> object:
    """Send one JSON request; failures raise `error` without response bodies."""
    request = urllib.request.Request(
        url,
        data=None if payload is None else json.dumps(payload).encode("utf-8"),
        method=method,
        headers=headers,
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read()
        return {} if allow_empty and not body else json.loads(body)
    except urllib.error.HTTPError as cause:
        raise error(f"{rejected} HTTP {cause.code}") from cause
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as cause:
        raise error(failed) from cause

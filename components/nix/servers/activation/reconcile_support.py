"""Validation and JSON-over-HTTPS helpers shared by the provider reconcilers."""

from __future__ import annotations

import json
import urllib.error
import urllib.request


class ReconcileError(RuntimeError):
    """An error that can be printed without exposing credentials."""


def require_mapping(value: object, label: str) -> dict:
    if not isinstance(value, dict):
        raise ReconcileError(f"{label} must be a mapping")
    return value


def require_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ReconcileError(f"{label} must be a non-empty string")
    return value


def request_json(
    url: str,
    *,
    method: str,
    headers: dict[str, str],
    rejected: str,
    failed: str,
    payload: dict | None = None,
    data: bytes | None = None,
    allow_empty: bool = False,
    timeout: int = 30,
) -> object:
    """Send one request with a JSON `payload` or raw `data` and decode its JSON reply.

    Failures raise ReconcileError without response bodies.
    """
    request = urllib.request.Request(
        url,
        data=data if payload is None else json.dumps(payload).encode("utf-8"),
        method=method,
        headers=headers,
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read()
        return {} if allow_empty and not body else json.loads(body)
    except urllib.error.HTTPError as cause:
        raise ReconcileError(f"{rejected} HTTP {cause.code}") from cause
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as cause:
        raise ReconcileError(failed) from cause

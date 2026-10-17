"""Bounded response observation redaction, safe to persist and log."""

from __future__ import annotations

import base64
import json
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import cast

from sentinel.regression.policy import canonical_json

_FIXED_SENSITIVE_HEADERS = {
    "authorization",
    "proxy-authorization",
    "cookie",
    "set-cookie",
    "x-api-key",
    "x-api-key-secret",
    "location",
}
_REDACTED = "[REDACTED]"
_MAX_HEADERS = 64
_MAX_HEADER_BYTES = 32_768


@dataclass(frozen=True, slots=True)
class RedactedObservation:
    status_code: int
    headers: dict[str, str]
    body_kind: str | None
    body_content: object | None
    source_bytes_captured: int
    truncated: bool
    redaction_unavailable: bool


def _pointer_parts(pointer: str) -> list[str]:
    if pointer == "":
        return []
    return [part.replace("~1", "/").replace("~0", "~") for part in pointer[1:].split("/")]


def _redact_pointer(document: object, parts: list[str]) -> object:
    if not parts:
        return _REDACTED
    if isinstance(document, dict) and parts[0] in document:
        key = parts[0]
        document[key] = _redact_pointer(document[key], parts[1:])
    elif isinstance(document, list) and parts[0].isdigit():
        index = int(parts[0])
        if 0 <= index < len(document):
            document[index] = _redact_pointer(document[index], parts[1:])
    return document


def redact_observation(
    *,
    status_code: int,
    headers: object,
    body: bytes | object | None,
    max_bytes: int,
    json_pointers: tuple[str, ...] = (),
    header_names: tuple[str, ...] = (),
) -> RedactedObservation:
    if max_bytes < 1:
        raise ValueError("max_bytes must be positive")
    safe_headers: dict[str, str] = {}
    configured = {name.lower() for name in header_names}
    if isinstance(headers, Mapping):
        iterable: list[object] = list(headers.items())
    elif isinstance(headers, (list, tuple)):
        iterable = list(headers)
    else:
        iterable = []
    aggregate_bytes = 0
    for item in iterable:
        if len(safe_headers) >= _MAX_HEADERS:
            break
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            continue
        name, value = item
        if not isinstance(name, str) or not isinstance(value, str):
            continue
        normalized = name.lower()
        safe_value = (
            _REDACTED if normalized in _FIXED_SENSITIVE_HEADERS | configured else value[:4096]
        )
        entry_bytes = len(normalized.encode("utf-8")) + len(safe_value.encode("utf-8"))
        if aggregate_bytes + entry_bytes > _MAX_HEADER_BYTES:
            break
        safe_headers[normalized] = safe_value
        aggregate_bytes += entry_bytes
    if body is None:
        return RedactedObservation(status_code, safe_headers, None, None, 0, False, False)

    if isinstance(body, bytes):
        source = body[:max_bytes]
        source_bytes = len(source)
        truncated = len(body) > max_bytes
        if json_pointers:
            try:
                parsed = json.loads(source.decode("utf-8"), parse_float=Decimal)
            except (UnicodeDecodeError, ValueError, TypeError):
                return RedactedObservation(
                    status_code, safe_headers, None, None, source_bytes, truncated, True
                )
            for pointer in json_pointers:
                parsed = _redact_pointer(parsed, _pointer_parts(pointer))
            try:
                content = cast(object, json.loads(canonical_json(parsed)))
            except (TypeError, ValueError):
                return RedactedObservation(
                    status_code, safe_headers, None, None, source_bytes, truncated, True
                )
            if len(canonical_json(content).encode("utf-8")) > max_bytes:
                return RedactedObservation(
                    status_code, safe_headers, None, None, source_bytes, truncated, True
                )
            return RedactedObservation(
                status_code, safe_headers, "json", content, source_bytes, truncated, False
            )
        try:
            text = source.decode("utf-8")
        except UnicodeDecodeError:
            encoded_binary = base64.b64encode(source).decode("ascii")
            return RedactedObservation(
                status_code,
                safe_headers,
                "bytes",
                encoded_binary[:max_bytes],
                source_bytes,
                truncated or len(encoded_binary) > max_bytes,
                False,
            )
        return RedactedObservation(
            status_code, safe_headers, "text", text[:max_bytes], source_bytes, truncated, False
        )

    try:
        document = json.loads(canonical_json(body), parse_float=Decimal)
    except (TypeError, ValueError):
        return RedactedObservation(status_code, safe_headers, None, None, 0, False, True)
    for pointer in json_pointers:
        document = _redact_pointer(document, _pointer_parts(pointer))
    try:
        encoded = canonical_json(document).encode("utf-8")
    except (TypeError, ValueError):
        return RedactedObservation(status_code, safe_headers, None, None, 0, False, True)
    truncated = len(encoded) > max_bytes
    if truncated:
        return RedactedObservation(status_code, safe_headers, None, None, max_bytes, True, True)
    return RedactedObservation(
        status_code, safe_headers, "json", document, len(encoded), False, False
    )

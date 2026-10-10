import base64
import binascii
import hashlib
import json
import re
from collections.abc import Iterable
from datetime import UTC, datetime
from uuid import UUID


class CursorInvalid(ValueError):
    pass


_CURSOR_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,2048}$")
_EMPTY_FILTER_FINGERPRINT = hashlib.sha256(b"{}").hexdigest()


def _unique_object(pairs: Iterable[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, item in pairs:
        if key in result:
            raise CursorInvalid
        result[key] = item
    return result


def _reject_constant(_: str) -> object:
    raise CursorInvalid


def _timestamp(value: datetime) -> str:
    if value.utcoffset() is None:
        raise ValueError("cursor timestamp must be timezone aware")
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def encode_project_cursor(after: tuple[datetime, UUID]) -> str:
    created_at, project_id = after
    payload = {
        "after": {"created_at": _timestamp(created_at), "id": str(project_id)},
        "cursor_version": 1,
        "filter_fingerprint": _EMPTY_FILTER_FINGERPRINT,
        "resource_kind": "projects",
        "scope_id": None,
    }
    canonical = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return base64.urlsafe_b64encode(canonical.encode("utf-8")).rstrip(b"=").decode("ascii")


def decode_project_cursor(value: str) -> tuple[datetime, UUID]:
    try:
        if not _CURSOR_PATTERN.fullmatch(value):
            raise CursorInvalid
        padding = "=" * (-len(value) % 4)
        decoded = base64.b64decode(value + padding, altchars=b"-_", validate=True)
        if len(decoded) > 1536:
            raise CursorInvalid
        payload = json.loads(
            decoded.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
        if not isinstance(payload, dict) or set(payload) != {
            "after",
            "cursor_version",
            "filter_fingerprint",
            "resource_kind",
            "scope_id",
        }:
            raise CursorInvalid
        if (
            payload["cursor_version"] != 1
            or payload["resource_kind"] != "projects"
            or payload["scope_id"] is not None
            or payload["filter_fingerprint"] != _EMPTY_FILTER_FINGERPRINT
        ):
            raise CursorInvalid
        after = payload["after"]
        if not isinstance(after, dict) or set(after) != {"created_at", "id"}:
            raise CursorInvalid
        created_text = after["created_at"]
        id_text = after["id"]
        if not isinstance(created_text, str) or not isinstance(id_text, str):
            raise CursorInvalid
        created_at = datetime.strptime(created_text, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)
        project_id = UUID(id_text)
        if str(project_id) != id_text or project_id.int == 0:
            raise CursorInvalid
        return created_at, project_id
    except (UnicodeDecodeError, binascii.Error, json.JSONDecodeError, ValueError, TypeError):
        raise CursorInvalid from None

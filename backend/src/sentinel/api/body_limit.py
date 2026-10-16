import json
from collections.abc import Iterable
from decimal import Decimal
from typing import cast

from starlette.datastructures import Headers
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from sentinel.api.problems import field_problem, problem


class InvalidJSON(ValueError):
    pass


PARSED_JSON_SCOPE_KEY = "sentinel.parsed_json"


def _closed_object(pairs: Iterable[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise InvalidJSON
        result[key] = value
    return result


def _reject_constant(_: str) -> object:
    raise InvalidJSON


def _contains_surrogate(value: object) -> bool:
    if isinstance(value, str):
        return any(0xD800 <= ord(character) <= 0xDFFF for character in value)
    if isinstance(value, list):
        return any(_contains_surrogate(item) for item in value)
    if isinstance(value, dict):
        return any(
            _contains_surrogate(key) or _contains_surrogate(item) for key, item in value.items()
        )
    return False


class BodyLimitMiddleware:
    def __init__(self, app: ASGIApp, *, max_bytes: int) -> None:
        self._app = app
        self._max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if not self._applies(scope):
            await self._app(scope, receive, send)
            return

        declared_length = Headers(scope=scope).get("content-length", "")
        if declared_length.isdecimal() and int(declared_length) > self._max_bytes:
            await problem(413, "request_too_large", "Request too large")(scope, receive, send)
            return

        headers = Headers(scope=scope)
        media_type = headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if media_type != "application/json":
            await problem(415, "unsupported_media_type", "Unsupported media type")(
                scope, receive, send
            )
            return

        chunks: list[bytes] = []
        received = 0
        while True:
            message = await receive()
            if message["type"] == "http.request":
                chunk = message.get("body", b"")
                received += len(chunk)
                if received > self._max_bytes:
                    await problem(413, "request_too_large", "Request too large")(
                        scope, receive, send
                    )
                    return
                chunks.append(chunk)
                if not message.get("more_body", False):
                    break
            elif message["type"] == "http.disconnect":
                return

        body = b"".join(chunks)
        try:
            parsed = cast(
                object,
                json.loads(
                    body.decode("utf-8"),
                    object_pairs_hook=_closed_object,
                    parse_constant=_reject_constant,
                    parse_float=Decimal,
                ),
            )
            if _contains_surrogate(parsed):
                raise InvalidJSON
        except (
            UnicodeDecodeError,
            json.JSONDecodeError,
            InvalidJSON,
            ValueError,
            RecursionError,
        ):
            await field_problem(
                422,
                "validation_failed",
                "Request validation failed",
                location="body",
                pointer="/",
                field_code="value_invalid",
            )(scope, receive, send)
            return

        scope.setdefault("state", {})[PARSED_JSON_SCOPE_KEY] = parsed

        sent = False

        async def replay() -> Message:
            nonlocal sent
            if sent:
                return {"type": "http.disconnect"}
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}

        await self._app(scope, replay, send)

    @staticmethod
    def _applies(scope: Scope) -> bool:
        return (
            scope["type"] == "http"
            and scope.get("method") in {"POST", "PUT", "PATCH"}
            and str(scope.get("path", "")).startswith("/api/v1/")
        )

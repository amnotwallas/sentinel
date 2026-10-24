"""Bounded, privacy-preserving direct lookup against Tempo's HTTP API."""

from __future__ import annotations

import base64
import binascii
import json
import re
import ssl
import threading
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import Any
from urllib.parse import unquote, urlsplit
from uuid import UUID

import httpx
from opentelemetry import trace
from opentelemetry.trace import Span, Tracer

from sentinel.telemetry.ports import (
    ContextContinuity,
    LinkedTrace,
    ServiceEvidence,
    TraceErrorCode,
    TraceLookup,
    TraceLookupPort,
    TraceLookupStatus,
)

TRACE_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
SPAN_ID_PATTERN = re.compile(r"^[0-9a-f]{16}$")
MAX_RESPONSE_BYTES = 1024 * 1024
MAX_SPANS = 256
MAX_SERVICES = 32
MAX_LINKED_TRACES = 16
MAX_TEXT_BYTES = 128
CONNECT_TIMEOUT_SECONDS = 1.0
READ_TIMEOUT_SECONDS = 2.0
WRITE_TIMEOUT_SECONDS = 1.0
TOTAL_TIMEOUT_SECONDS = 2.0

_SERVICE_ATTRIBUTES = {
    "service.name": "name",
    "service.version": "version",
    "deployment.environment": "environment",
    "deployment.environment.name": "environment",
    "service.revision": "revision",
    "deployment.revision": "revision",
    "deployment.source.revision": "revision",
}


class TempoEndpointError(ValueError):
    """The operator-supplied internal Tempo endpoint is unsafe or unsupported."""

    def __init__(self) -> None:
        super().__init__("tempo_url_invalid")


class TempoTLSConfigurationError(ValueError):
    """TLS verification cannot be disabled for Tempo queries."""

    def __init__(self) -> None:
        super().__init__("tls_verification_required")


class _OversizedResponse(Exception):
    pass


class _DeadlineExpired(Exception):
    pass


def validate_tempo_url(value: str) -> str:
    """Validate an internal base URL without treating it as a browser URL."""
    if not isinstance(value, str) or not value or any(character.isspace() for character in value):
        raise TempoEndpointError
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
        _ = parsed.port
    except ValueError:
        raise TempoEndpointError from None
    if parsed.scheme not in {"http", "https"} or hostname is None:
        raise TempoEndpointError
    if parsed.username is not None or parsed.password is not None:
        raise TempoEndpointError
    if parsed.query or parsed.fragment:
        raise TempoEndpointError
    if any(part in {".", ".."} for part in unquote(parsed.path).split("/")):
        raise TempoEndpointError
    return value.rstrip("/")


def _valid_trace_id(value: object) -> bool:
    return (
        isinstance(value, str)
        and TRACE_ID_PATTERN.fullmatch(value) is not None
        and set(value) != {"0"}
    )


def _valid_span_id(value: object) -> bool:
    return (
        isinstance(value, str)
        and SPAN_ID_PATTERN.fullmatch(value) is not None
        and set(value) != {"0"}
    )


def _tempo_id(value: object, size: int) -> str | None:
    if not isinstance(value, str):
        return None
    if len(value) == size * 2 and re.fullmatch(r"[0-9a-f]+", value) is not None:
        return value if set(value) != {"0"} else None
    try:
        decoded = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError):
        return None
    if len(decoded) != size or not any(decoded):
        return None
    return decoded.hex()


def _bounded_text(value: object) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        encoded = value.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        return None
    if len(encoded) > MAX_TEXT_BYTES or any(ord(char) < 0x20 for char in value):
        return None
    return value


def _string_attributes(value: object) -> Iterator[tuple[str, str]]:
    if not isinstance(value, list):
        return
    for attribute in value:
        if not isinstance(attribute, dict):
            continue
        key = attribute.get("key")
        raw_value = attribute.get("value")
        if not isinstance(key, str) or not isinstance(raw_value, dict):
            continue
        string_value = _bounded_text(raw_value.get("stringValue"))
        if string_value is not None:
            yield key, string_value


def _resource_evidence(resource: object) -> ServiceEvidence | None:
    if not isinstance(resource, dict):
        return None
    values: dict[str, str] = {}
    for key, value in _string_attributes(resource.get("attributes")):
        field = _SERVICE_ATTRIBUTES.get(key)
        if field is not None and field not in values:
            values[field] = value
    name = values.get("name")
    return (
        ServiceEvidence(
            name=name,
            version=values.get("version"),
            environment=values.get("environment"),
            revision=values.get("revision"),
        )
        if name is not None
        else None
    )


def _status_is_error(span: dict[str, Any]) -> bool:
    status = span.get("status")
    if not isinstance(status, dict):
        return False
    code = status.get("code")
    return isinstance(code, (int, str)) and code in {2, "2", "STATUS_CODE_ERROR", "ERROR"}


def _ordered_services(services: set[ServiceEvidence]) -> tuple[ServiceEvidence, ...]:
    return tuple(
        sorted(
            services,
            key=lambda item: (
                item.name,
                item.version or "",
                item.environment or "",
                item.revision or "",
            ),
        )[:MAX_SERVICES]
    )


class TempoLookupAdapter(TraceLookupPort):
    """Direct trace-ID adapter with fixed bounds and closed safe outcomes."""

    def __init__(
        self,
        base_url: str,
        *,
        verify: bool | ssl.SSLContext = True,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        tracer: Tracer | None = None,
    ) -> None:
        if verify is False:
            raise TempoTLSConfigurationError
        self.base_url = validate_tempo_url(base_url)
        self._clock = clock
        self._tracer = tracer or trace.get_tracer(__name__)
        self._client = httpx.Client(
            base_url=self.base_url,
            follow_redirects=False,
            headers={"accept": "application/json"},
            timeout=httpx.Timeout(
                TOTAL_TIMEOUT_SECONDS,
                connect=CONNECT_TIMEOUT_SECONDS,
                read=READ_TIMEOUT_SECONDS,
                write=WRITE_TIMEOUT_SECONDS,
            ),
            trust_env=False,
            verify=verify,
            transport=transport,
            limits=httpx.Limits(max_connections=4, max_keepalive_connections=4),
        )
        self._search_supported: bool | None = None
        self._capability_lock = threading.Lock()

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> TempoLookupAdapter:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _remaining(self, deadline: datetime) -> float:
        now = self._clock()
        if now.tzinfo is None:
            now = now.replace(tzinfo=UTC)
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=UTC)
        remaining = (deadline - now).total_seconds()
        if remaining <= 0:
            raise _DeadlineExpired
        return min(TOTAL_TIMEOUT_SECONDS, remaining)

    @staticmethod
    def _result(
        trace_id: str,
        *,
        status: TraceLookupStatus,
        error_code: TraceErrorCode | None,
        response_size_bytes: int = 0,
        client_span_id: str | None = None,
        trace_span_count: int = 0,
        error_span_count: int = 0,
        services: tuple[ServiceEvidence, ...] = (),
        context_continuity: ContextContinuity = ContextContinuity.UNKNOWN,
    ) -> TraceLookup:
        return TraceLookup(
            trace_id=trace_id,
            client_span_id=client_span_id,
            status=status,
            error_code=error_code,
            trace_span_count=trace_span_count,
            error_span_count=error_span_count,
            services=services,
            context_continuity=context_continuity,
            response_size_bytes=response_size_bytes,
        )

    def lookup(
        self,
        trace_id: str,
        *,
        expected_span_id: str,
        deadline: datetime,
    ) -> TraceLookup:
        with self._tracer.start_as_current_span(
            "sentinel.tempo.lookup",
            record_exception=False,
            set_status_on_exception=False,
        ) as span:
            result = self._lookup(trace_id, expected_span_id=expected_span_id, deadline=deadline)
            span.set_attribute("sentinel.outcome", result.status.value)
            if result.error_code is not None:
                span.set_attribute("sentinel.error_code", result.error_code.value)
            span.set_attribute("sentinel.response.size", result.response_size_bytes)
            return result

    def _lookup(
        self,
        trace_id: str,
        *,
        expected_span_id: str,
        deadline: datetime,
    ) -> TraceLookup:
        if not _valid_trace_id(trace_id) or not _valid_span_id(expected_span_id):
            raise ValueError("invalid trace identity")
        path = f"api/traces/{trace_id}"
        try:
            self._remaining(deadline)
            with self._client.stream("GET", path) as response:
                if response.status_code == 404:
                    return self._result(
                        trace_id,
                        status=TraceLookupStatus.MISSING,
                        error_code=TraceErrorCode.NOT_FOUND,
                    )
                if 300 <= response.status_code < 400:
                    return self._result(
                        trace_id,
                        status=TraceLookupStatus.TEMPO_UNAVAILABLE,
                        error_code=TraceErrorCode.UNSUPPORTED,
                    )
                if response.status_code >= 500:
                    return self._result(
                        trace_id,
                        status=TraceLookupStatus.TEMPO_UNAVAILABLE,
                        error_code=TraceErrorCode.UNAVAILABLE,
                    )
                if response.status_code != 200:
                    return self._result(
                        trace_id,
                        status=TraceLookupStatus.TEMPO_UNAVAILABLE,
                        error_code=TraceErrorCode.BAD_RESPONSE,
                    )
                body = self._read_body(response, deadline)
        except _OversizedResponse:
            return self._result(
                trace_id,
                status=TraceLookupStatus.PARTIAL,
                error_code=TraceErrorCode.OVERSIZED_RESPONSE,
            )
        except (_DeadlineExpired, httpx.TimeoutException):
            return self._result(
                trace_id,
                status=TraceLookupStatus.TEMPO_UNAVAILABLE,
                error_code=TraceErrorCode.TIMEOUT,
            )
        except httpx.HTTPError:
            return self._result(
                trace_id,
                status=TraceLookupStatus.TEMPO_UNAVAILABLE,
                error_code=TraceErrorCode.TRANSPORT_ERROR,
            )
        except Exception:
            return self._result(
                trace_id,
                status=TraceLookupStatus.TEMPO_UNAVAILABLE,
                error_code=TraceErrorCode.TRANSPORT_ERROR,
            )
        try:
            return self._parse(trace_id, expected_span_id, body)
        except Exception:
            # Parser failures remain a closed, bounded outcome; raw payloads never escape.
            return self._result(
                trace_id,
                status=TraceLookupStatus.PARTIAL,
                error_code=TraceErrorCode.INVALID_TRACE,
                response_size_bytes=len(body),
            )

    def _read_body(self, response: httpx.Response, deadline: datetime) -> bytes:
        body = bytearray()
        for chunk in response.iter_bytes():
            self._remaining(deadline)
            body.extend(chunk)
            if len(body) > MAX_RESPONSE_BYTES:
                raise _OversizedResponse
        return bytes(body)

    def _parse(self, trace_id: str, expected_span_id: str, body: bytes) -> TraceLookup:
        size = len(body)
        try:
            document = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return self._result(
                trace_id,
                status=TraceLookupStatus.PARTIAL,
                error_code=TraceErrorCode.INVALID_TRACE,
                response_size_bytes=size,
            )
        if not isinstance(document, dict):
            return self._result(
                trace_id,
                status=TraceLookupStatus.PARTIAL,
                error_code=TraceErrorCode.INVALID_TRACE,
                response_size_bytes=size,
            )
        batches = document.get("batches")
        if not isinstance(batches, list):
            return self._result(
                trace_id,
                status=TraceLookupStatus.PARTIAL,
                error_code=TraceErrorCode.INVALID_TRACE,
                response_size_bytes=size,
            )
        spans: list[dict[str, Any]] = []
        services: set[ServiceEvidence] = set()
        malformed = False
        for batch in batches:
            if not isinstance(batch, dict):
                malformed = True
                continue
            service = _resource_evidence(batch.get("resource"))
            if service is not None:
                services.add(service)
            scope_spans = batch.get("scopeSpans")
            if not isinstance(scope_spans, list):
                malformed = True
                continue
            for scope in scope_spans:
                if not isinstance(scope, dict):
                    malformed = True
                    continue
                scope_items = scope.get("spans")
                if not isinstance(scope_items, list):
                    malformed = True
                    continue
                for span in scope_items:
                    if not isinstance(span, dict):
                        malformed = True
                        continue
                    if len(spans) >= MAX_SPANS:
                        return self._result(
                            trace_id,
                            status=TraceLookupStatus.PARTIAL,
                            error_code=TraceErrorCode.OVERSIZED_RESPONSE,
                            response_size_bytes=size,
                            trace_span_count=MAX_SPANS,
                            services=_ordered_services(services),
                            context_continuity=ContextContinuity.UNKNOWN,
                        )
                    spans.append(span)
        valid_spans: list[dict[str, Any]] = []
        for span in spans:
            normalized_trace_id = _tempo_id(span.get("traceId"), 16)
            normalized_span_id = _tempo_id(span.get("spanId"), 8)
            if normalized_trace_id != trace_id or normalized_span_id is None:
                continue
            normalized_span = dict(span)
            normalized_span["traceId"] = normalized_trace_id
            normalized_span["spanId"] = normalized_span_id
            valid_spans.append(normalized_span)
        matching = next(
            (span for span in valid_spans if span.get("spanId") == expected_span_id), None
        )
        if not valid_spans:
            return self._result(
                trace_id,
                status=TraceLookupStatus.PARTIAL,
                error_code=TraceErrorCode.INVALID_TRACE,
                response_size_bytes=size,
                context_continuity=ContextContinuity.UNKNOWN,
            )
        error_count = sum(1 for span in valid_spans if _status_is_error(span))
        ordered_services = tuple(
            sorted(
                services,
                key=lambda item: (
                    item.name,
                    item.version or "",
                    item.environment or "",
                    item.revision or "",
                ),
            )
        )
        service_overflow = len(ordered_services) > MAX_SERVICES
        bounded_services = _ordered_services(services)
        return self._result(
            trace_id,
            status=(
                TraceLookupStatus.AVAILABLE
                if matching is not None and not malformed and not service_overflow
                else TraceLookupStatus.PARTIAL
            ),
            error_code=(
                TraceErrorCode.INVALID_TRACE
                if malformed
                else TraceErrorCode.OVERSIZED_RESPONSE
                if service_overflow
                else None
            ),
            response_size_bytes=size,
            client_span_id=expected_span_id if matching is not None else None,
            trace_span_count=len(valid_spans),
            error_span_count=error_count,
            services=bounded_services,
            context_continuity=(
                ContextContinuity.CONNECTED
                if matching is not None and not malformed and not service_overflow
                else ContextContinuity.BROKEN
            ),
        )

    def search_supported(self) -> bool:
        """Probe optional indexed search once; direct lookup never depends on it."""
        with self._capability_lock:
            if self._search_supported is not None:
                return self._search_supported
            supported = False
            try:
                with self._client.stream("GET", "api/search/tags?scope=span") as response:
                    if 200 <= response.status_code < 300:
                        body = bytearray()
                        for chunk in response.iter_bytes():
                            body.extend(chunk)
                            if len(body) > MAX_RESPONSE_BYTES:
                                break
                        supported = len(body) <= MAX_RESPONSE_BYTES
            except Exception:
                supported = False
            self._search_supported = supported
            return supported

    def search_attempt(
        self,
        attempt_id: UUID,
        *,
        start_at: datetime,
        end_at: datetime,
        limit: int,
    ) -> tuple[LinkedTrace, ...]:
        with self._tracer.start_as_current_span(
            "sentinel.tempo.search",
            record_exception=False,
            set_status_on_exception=False,
        ) as span:
            results = self._search_attempt(
                attempt_id, start_at=start_at, end_at=end_at, limit=limit, span=span
            )
            span.set_attribute("sentinel.outcome", "available" if results else "empty")
            return results

    def _search_attempt(
        self,
        attempt_id: UUID,
        *,
        start_at: datetime,
        end_at: datetime,
        limit: int,
        span: Span,
    ) -> tuple[LinkedTrace, ...]:
        """Return only bounded results of the exact attempt-baggage search."""
        limit = min(max(limit, 0), MAX_LINKED_TRACES)
        if limit == 0:
            span.set_attribute("sentinel.response.size", 0)
            return ()
        try:
            self._remaining(end_at)
            with self._client.stream(
                "GET",
                "api/search",
                params={
                    "tags": f"sentinel.attempt.id={attempt_id}",
                    "start": str(int(start_at.timestamp())),
                    "end": str(int(end_at.timestamp())),
                    "limit": str(limit),
                },
            ) as response:
                if response.status_code != 200:
                    span.set_attribute("sentinel.response.size", 0)
                    return ()
                body = self._read_body(response, end_at)
                span.set_attribute("sentinel.response.size", len(body))
        except Exception:
            span.set_attribute("sentinel.response.size", 0)
            return ()
        try:
            document = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return ()
        if not isinstance(document, dict) or not isinstance(document.get("traces"), list):
            return ()

        matches: dict[str, set[ServiceEvidence]] = {}
        for trace_document in document["traces"]:
            if not isinstance(trace_document, dict):
                continue
            raw_trace_id = trace_document.get("traceID")
            if not isinstance(raw_trace_id, str):
                continue
            trace_id = raw_trace_id.lower()
            if not _valid_trace_id(trace_id):
                continue
            services = matches.setdefault(trace_id, set())
            span_sets = trace_document.get("spanSets", trace_document.get("spanSet", []))
            if isinstance(span_sets, dict):
                span_sets = [span_sets]
            if not isinstance(span_sets, list):
                continue
            for span_set in span_sets:
                if not isinstance(span_set, dict) or not isinstance(span_set.get("spans"), list):
                    continue
                for span in span_set["spans"]:
                    if not isinstance(span, dict):
                        continue
                    values: dict[str, str] = {}
                    for key, value in _string_attributes(span.get("attributes")):
                        field = _SERVICE_ATTRIBUTES.get(key)
                        if field is not None and field not in values:
                            values[field] = value
                    if "name" in values:
                        services.add(
                            ServiceEvidence(
                                name=values["name"],
                                version=values.get("version"),
                                environment=values.get("environment"),
                                revision=values.get("revision"),
                            )
                        )
        return tuple(
            LinkedTrace(trace_id=trace_id, services=_ordered_services(matches[trace_id]))
            for trace_id in sorted(matches)[:limit]
        )

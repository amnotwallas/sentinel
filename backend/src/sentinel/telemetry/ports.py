"""Telemetry application ports and bounded lookup results."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID


class TraceLookupStatus(StrEnum):
    AVAILABLE = "available"
    PARTIAL = "partial"
    MISSING = "missing"
    TEMPO_UNAVAILABLE = "tempo_unavailable"


class TraceErrorCode(StrEnum):
    NOT_FOUND = "not_found"
    UNAVAILABLE = "unavailable"
    TIMEOUT = "timeout"
    BAD_RESPONSE = "bad_response"
    OVERSIZED_RESPONSE = "oversized_response"
    UNSUPPORTED = "unsupported"
    TRANSPORT_ERROR = "transport_error"
    INVALID_TRACE = "invalid_trace"


class ContextContinuity(StrEnum):
    CONNECTED = "connected"
    BROKEN = "broken"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ServiceEvidence:
    name: str
    version: str | None = None
    environment: str | None = None
    revision: str | None = None


@dataclass(frozen=True, slots=True)
class TraceLookup:
    """Safe, derived direct-lookup output; no Tempo payload crosses this port."""

    trace_id: str
    client_span_id: str | None
    status: TraceLookupStatus
    error_code: TraceErrorCode | None
    trace_span_count: int
    error_span_count: int
    services: tuple[ServiceEvidence, ...]
    context_continuity: ContextContinuity
    response_size_bytes: int


@dataclass(frozen=True, slots=True)
class LinkedTrace:
    """Safe result of an exact baggage-attribute search."""

    trace_id: str
    services: tuple[ServiceEvidence, ...] = ()


class TraceLookupPort(Protocol):
    def lookup(
        self,
        trace_id: str,
        *,
        expected_span_id: str,
        deadline: datetime,
    ) -> TraceLookup: ...

    def search_supported(self) -> bool: ...

    def search_attempt(
        self,
        attempt_id: UUID,
        *,
        start_at: datetime,
        end_at: datetime,
        limit: int,
    ) -> tuple[LinkedTrace, ...]: ...


class LinkedTraceSearchPort(Protocol):
    def search_attempt(
        self,
        attempt_id: UUID,
        *,
        start_at: datetime,
        end_at: datetime,
        limit: int,
    ) -> tuple[LinkedTrace, ...]: ...


Clock = Callable[[], datetime]

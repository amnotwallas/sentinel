"""Safe trace-reference domain values used by persistence and later adapters."""

from enum import StrEnum


class TraceRelation(StrEnum):
    PRIMARY = "primary"
    LINKED = "linked"


class CorrelationSource(StrEnum):
    SENTINEL_CONTEXT = "sentinel_context"
    BAGGAGE_ATTRIBUTE_SEARCH = "baggage_attribute_search"


class TraceReferenceStatus(StrEnum):
    PENDING = "pending"
    MISSING = "missing"
    AVAILABLE = "available"
    PARTIAL = "partial"
    TEMPO_UNAVAILABLE = "tempo_unavailable"
    EXPIRED = "expired"

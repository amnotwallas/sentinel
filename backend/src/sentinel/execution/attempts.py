"""Attempt lifecycle domain records and explicit adapter-facing ports."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sentinel.execution.domain import (
    AttemptState,
    DispatchCertainty,
    PreparationErrorCode,
    RedirectRejectionCode,
    TransportOutcome,
)


@dataclass(frozen=True, slots=True)
class AttemptRecord:
    id: UUID
    execution_item_id: UUID
    sequence: int
    state: AttemptState
    dispatch_certainty: DispatchCertainty
    request_fingerprint: str | None
    created_at: datetime
    dispatch_recorded_at: datetime | None
    response_recorded_at: datetime | None
    finished_at: datetime | None
    duration_ms: int | None
    transport_outcome: TransportOutcome | None
    preparation_error_code: PreparationErrorCode | None
    redirect_rejection_code: RedirectRejectionCode | None
    replay_successor_id: UUID | None
    primary_trace_id: str | None
    client_span_id: str | None
    included_in_verdict: bool
    result_contract_version: int = 0
    verdict: str | None = None
    evaluation_error_code: str | None = None


@dataclass(frozen=True, slots=True)
class ResponseArtifact:
    attempt_id: UUID
    status_code: int
    headers: dict[str, object]
    body_kind: str | None
    body_content: object | None
    source_bytes_captured: int
    truncated: bool
    redaction_unavailable: bool
    recorded_at: datetime
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class TraceReferenceRecord:
    id: UUID
    relation: str
    trace_id: str
    span_id: str | None
    correlation_source: str
    status: str
    first_checked_at: datetime | None
    last_checked_at: datetime | None
    deadline_at: datetime
    lookup_attempt_count: int
    last_error_code: str | None
    evidence_json: dict[str, object] | None

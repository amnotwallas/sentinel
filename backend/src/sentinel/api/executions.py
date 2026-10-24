from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Any, Literal, cast
from uuid import UUID

from fastapi import APIRouter, Header, Path, Query, Response
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_serializer,
    field_validator,
    model_validator,
)
from pydantic.json_schema import SkipJsonSchema
from sqlalchemy.exc import IntegrityError, OperationalError

from sentinel.api.problems import Problem, field_problem, problem
from sentinel.execution.attempts import AttemptRecord, ResponseArtifact, TraceReferenceRecord
from sentinel.execution.creation import (
    AttemptReadRecord,
    ExecutionCreateCommand,
    ExecutionIdempotencyConflict,
    ExecutionInfrastructureError,
    ExecutionRecord,
    ExecutionResourceNotFound,
    ExecutionValidationError,
    PostgresExecutionService,
)
from sentinel.regression.policy import canonical_json
from sentinel.regression.read_models import ComparisonRead, EvaluationRead, PromotionRead

_UUID_PATTERN = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
_IDEMPOTENCY_PATTERN = re.compile(r"^[\x21-\x7e]{1,128}$")
_PROBLEMS: dict[int | str, dict[str, Any]] = {
    status: {
        "model": Problem,
        "description": "RFC 9457 problem response",
        "content": {"application/problem+json": {}},
    }
    for status in (401, 403, 404, 409, 413, 415, 422, 500)
}
_LOCATION_HEADER: dict[str, Any] = {
    "schema": {"type": "string"},
    "description": "Created resource path",
}
_CURSOR_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,2048}$")


class ExecutionStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class ItemStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    INDETERMINATE = "indeterminate"
    FAILED = "failed"
    SKIPPED = "skipped"


class Verdict(StrEnum):
    PASSED = "passed"
    FUNCTIONAL_REGRESSION = "functional_regression"
    PERFORMANCE_WARNING = "performance_warning"
    OBSERVED_CHANGE = "observed_change"
    INCONCLUSIVE = "inconclusive"
    BASELINE_REQUIRED = "baseline_required"
    NOT_EVALUATED = "not_evaluated"


class AttemptState(StrEnum):
    PREPARED = "prepared"
    DISPATCHING = "dispatching"
    RESPONSE_RECEIVED = "response_received"
    TRANSPORT_FAILED = "transport_failed"
    EVALUATED = "evaluated"
    REPLAY_SCHEDULED = "replay_scheduled"
    INDETERMINATE = "indeterminate"
    FAILED = "failed"


class DispatchCertainty(StrEnum):
    NOT_STARTED = "not_started"
    NOT_SENT = "not_sent"
    POSSIBLY_SENT = "possibly_sent"
    RESPONSE_RECEIVED = "response_received"


class TransportOutcome(StrEnum):
    RESPONSE_RECEIVED = "response_received"
    DNS_FAILURE = "dns_failure"
    CONNECT_TIMEOUT = "connect_timeout"
    CONNECTION_FAILURE = "connection_failure"
    TLS_FAILURE = "tls_failure"
    WRITE_TIMEOUT = "write_timeout"
    WRITE_FAILURE = "write_failure"
    READ_TIMEOUT = "read_timeout"
    READ_FAILURE = "read_failure"
    TOTAL_TIMEOUT = "total_timeout"
    TARGET_DENIED = "target_denied"
    REDIRECT_DENIED = "redirect_denied"
    RESPONSE_LIMIT_EXCEEDED = "response_limit_exceeded"
    INDETERMINATE = "indeterminate"


class PreparationErrorCode(StrEnum):
    SECRET_MISSING = "secret_missing"
    TEMPLATE_VARIABLE_MISSING = "template_variable_missing"
    TARGET_POLICY_DENIED = "target_policy_denied"
    REQUEST_INVALID = "request_invalid"
    TLS_VERIFICATION_REQUIRED = "tls_verification_required"
    INFRASTRUCTURE_FAILURE = "infrastructure_failure"


class RedirectRejectionCode(StrEnum):
    METHOD_NOT_ALLOWED = "method_not_allowed"
    LOCATION_MISSING = "location_missing"
    LOCATION_INVALID = "location_invalid"
    SCHEME_DENIED = "scheme_denied"
    PORT_DENIED = "port_denied"
    TARGET_DENIED = "target_denied"
    REDIRECT_LIMIT_EXCEEDED = "redirect_limit_exceeded"


class ObservationState(StrEnum):
    NOT_RECORDED = "not_recorded"
    AVAILABLE = "available"
    EXPIRED = "expired"
    OMITTED = "omitted"


def _timestamp(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class TimestampModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_serializer(
        "created_at",
        "started_at",
        "finished_at",
        "dispatch_recorded_at",
        "response_recorded_at",
        "recorded_at",
        "expires_at",
        "first_checked_at",
        "last_checked_at",
        "deadline_at",
        when_used="unless-none",
        check_fields=False,
    )
    def serialize_timestamp(self, value: datetime) -> str:
        return _timestamp(value)


def _execution_create_schema(schema: dict[str, Any]) -> None:
    schema["oneOf"] = [
        {
            "required": ["environment_id", "test_case_id"],
            "not": {"required": ["suite_id"]},
        },
        {
            "required": ["environment_id", "suite_id"],
            "not": {"required": ["test_case_id"]},
        },
    ]


class ExecutionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_extra=_execution_create_schema)

    environment_id: UUID
    # Explicit null is rejected by the closed-body validator. SkipJsonSchema
    # keeps the wire contract absent-or-present rather than nullable.
    test_case_id: UUID | SkipJsonSchema[None] = None
    suite_id: UUID | SkipJsonSchema[None] = None

    @model_validator(mode="before")
    @classmethod
    def closed_one_of(cls, values: object) -> object:
        if not isinstance(values, dict):
            return values
        keys = set(values)
        if keys == {"environment_id", "test_case_id"} and values.get("test_case_id") is not None:
            return values
        if keys == {"environment_id", "suite_id"} and values.get("suite_id") is not None:
            return values
        raise ValueError("exactly one non-null source is required")

    @model_validator(mode="after")
    def exactly_one_source(self) -> ExecutionCreate:
        if (self.test_case_id is None) == (self.suite_id is None):
            raise ValueError("exactly one source is required")
        if self.environment_id.int == 0:
            raise ValueError("environment_id is invalid")
        if self.test_case_id is not None and self.test_case_id.int == 0:
            raise ValueError("test_case_id is invalid")
        if self.suite_id is not None and self.suite_id.int == 0:
            raise ValueError("suite_id is invalid")
        return self


class RelativeLinks(BaseModel):
    model_config = ConfigDict(extra="forbid")
    self: str = Field(pattern=r"^/api/v1/(?:executions|attempts)/[0-9a-f-]+$")


class ChangeEventSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    changed_fields: list[
        Literal[
            "name",
            "base_url",
            "variables",
            "secret_references",
            "target_policy",
            "request",
            "assertions",
            "comparison_policy",
            "redaction",
            "allow_unsafe_replay",
            "suite_items",
            "baseline_activation",
        ]
    ] = Field(max_length=16)


class ChangeEventOutput(TimestampModel):
    id: UUID
    project_id: UUID
    kind: Literal[
        "environment_created",
        "environment_updated",
        "test_case_created",
        "test_case_revised",
        "suite_created",
        "suite_revised",
        "baseline_activated",
    ]
    subject_type: Literal["environment", "test_case", "suite", "baseline"]
    subject_id: UUID
    before_ref: UUID | None
    after_ref: UUID | None
    summary: ChangeEventSummary
    created_at: datetime


class AttemptSummary(TimestampModel):
    id: UUID
    sequence: int = Field(ge=1, le=2_147_483_647)
    state: AttemptState
    verdict: Verdict | None
    created_at: datetime
    dispatch_recorded_at: datetime | None
    response_recorded_at: datetime | None
    finished_at: datetime | None
    duration_ms: int | None = Field(ge=0)
    dispatch_certainty: DispatchCertainty
    transport_outcome: TransportOutcome | None
    preparation_error_code: PreparationErrorCode | None
    redirect_rejection_code: RedirectRejectionCode | None
    primary_trace_id: str | None = Field(pattern=r"^[0-9a-f]{32}$")
    client_span_id: str | None = Field(pattern=r"^[0-9a-f]{16}$")
    replayed_by_attempt_id: UUID | None
    included_in_verdict: bool
    links: RelativeLinks


def _safe_evidence_text(value: str | None) -> str | None:
    if value is None:
        return None
    if (
        not value
        or len(value.encode("utf-8")) > 128
        or any(ord(character) < 0x20 or ord(character) == 0x7F for character in value)
    ):
        raise ValueError("invalid trace evidence text")
    return value


class TraceServiceEvidenceOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=128)
    version: str | None = Field(default=None, max_length=128)
    environment: str | None = Field(default=None, max_length=128)
    revision: str | None = Field(default=None, max_length=128)

    _validate_text = field_validator("name", "version", "environment", "revision")(
        _safe_evidence_text
    )


class TraceDeploymentEvidenceOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    service: str = Field(min_length=1, max_length=128)
    environment: str | None = Field(default=None, max_length=128)
    revision: str | None = Field(default=None, max_length=128)

    _validate_text = field_validator("service", "environment", "revision")(_safe_evidence_text)


class ComparisonAnchorChangeOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=128)
    fields: list[Literal["name", "version", "environment", "revision"]] = Field(
        min_length=1, max_length=4
    )

    _validate_name = field_validator("name")(_safe_evidence_text)


class ComparisonAnchorOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reference_id: UUID
    changed: list[ComparisonAnchorChangeOutput] = Field(max_length=32)


class TraceEvidenceOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    primary_span_found: bool
    trace_span_count: int = Field(ge=0, le=256)
    error_span_count: int = Field(ge=0, le=256)
    services: list[TraceServiceEvidenceOutput] = Field(max_length=32)
    deployments: list[TraceDeploymentEvidenceOutput] = Field(max_length=32)
    linked_match_count: int = Field(ge=0, le=16)
    context_continuity: Literal["connected", "broken", "unknown"]
    comparison_anchor: ComparisonAnchorOutput | None


class TraceReferenceOutput(TimestampModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    relation: Literal["primary", "linked"]
    trace_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    span_id: str | None = Field(pattern=r"^[0-9a-f]{16}$")
    correlation_source: Literal["sentinel_context", "baggage_attribute_search"]
    status: Literal["pending", "missing", "available", "partial", "tempo_unavailable", "expired"]
    first_checked_at: datetime | None
    last_checked_at: datetime | None
    deadline_at: datetime | None
    lookup_attempt_count: int = Field(ge=0, le=7)
    last_error_code: (
        Literal[
            "not_found",
            "unavailable",
            "timeout",
            "bad_response",
            "oversized_response",
            "unsupported",
            "transport_error",
            "invalid_trace",
            "correlation_delivery_exhausted",
        ]
        | None
    )
    evidence: TraceEvidenceOutput | None
    tempo_url: str | None = Field(max_length=2048, pattern=r"^https?://")


class ResponseHeader(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(
        min_length=1,
        max_length=256,
        pattern=r"^[!#$%&'*+.^_`|~0-9a-z-]+$",
    )
    value: str = Field(max_length=8192, pattern=r"^[^\x00\r\n]*$")


class ResponseObservation(TimestampModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    status_code: int | None = Field(ge=100, le=599)
    headers: list[ResponseHeader] = Field(max_length=64)
    body_kind: Literal["json", "text", "omitted"]
    body: str | None = Field(max_length=1_048_576)
    captured_bytes: int = Field(ge=0, le=1_048_576)
    truncated: bool
    redaction_unavailable: bool
    recorded_at: datetime
    expires_at: datetime


class BaselineComparisonOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state: Literal[
        "not_requested", "pending", "not_evaluated", "missing", "incompatible", "compatible"
    ]
    baseline_activation_id: UUID | None
    baseline_id: UUID | None
    baseline_version: int | None = Field(ge=1)
    policy_fingerprint: str | None = Field(pattern=r"^[0-9a-f]{64}$")
    checked_at: datetime | None


class EvaluationOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    ordinal: int = Field(ge=0, le=256)
    kind: Literal["assertion", "baseline_selector", "performance"]
    rule_id: UUID | None
    severity: Literal["required", "advisory"]
    outcome: Literal["passed", "failed", "unevaluable", "not_evaluated"]
    message_code: Literal[
        "assertion_passed",
        "selected_value_match",
        "duration_within_threshold",
        "status_mismatch",
        "header_missing",
        "header_mismatch",
        "json_missing",
        "json_unexpected",
        "json_type_mismatch",
        "json_value_mismatch",
        "text_mismatch",
        "invalid_json",
        "selected_value_mismatch",
        "normalizer_input_invalid",
        "baseline_missing",
        "baseline_incompatible",
        "content_missing",
        "content_expired",
        "content_truncated",
        "content_redacted",
        "duration_exceeded",
        "not_evaluated",
    ]
    expected: object | None
    actual: object | None
    evidence_omitted: bool


class BaselinePromotionOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    eligible: bool
    warning_codes: list[
        Literal[
            "missing_baseline",
            "incompatible_baseline",
            "observed_change",
            "performance_warning",
        ]
    ] = Field(max_length=4)
    ineligibility_codes: list[
        Literal[
            "no_selectors",
            "attempt_not_evaluated",
            "attempt_not_included",
            "required_functional_check_failed",
            "evaluation_inconclusive",
            "selected_value_unavailable",
            "selected_value_too_large",
            "policy_mismatch",
            "scope_mismatch",
        ]
    ] = Field(max_length=9)


class AttemptDetail(AttemptSummary):
    model_config = ConfigDict(extra="forbid")

    execution_id: UUID
    execution_item_id: UUID
    request_fingerprint: str | None = Field(pattern=r"^[0-9a-f]{64}$")
    observation: ResponseObservation | None
    observation_state: ObservationState
    baseline_comparison: BaselineComparisonOutput
    evaluations: list[EvaluationOutput] = Field(max_length=257)
    evaluation_error_code: Literal["platform_evaluation_failure"] | None
    baseline_promotion: BaselinePromotionOutput
    trace_references: list[TraceReferenceOutput] = Field(max_length=17)
    trace_references_truncated: bool


class ExecutionItem(TimestampModel):
    id: UUID
    ordinal: int = Field(ge=0, le=99)
    test_case_id: UUID
    test_case_revision_id: UUID
    test_case_revision_version: int = Field(ge=1)
    status: ItemStatus
    verdict: Verdict | None
    started_at: datetime | None
    finished_at: datetime | None
    attempts: list[AttemptSummary] = Field(max_length=100)
    attempts_truncated: bool
    attempt_count: int = Field(ge=0)


class ExecutionSummary(TimestampModel):
    id: UUID
    project_id: UUID
    environment_id: UUID
    environment_revision_id: UUID
    source_type: Literal["test_case", "suite"]
    source_id: UUID
    source_revision_id: UUID
    status: ExecutionStatus
    verdict: Verdict | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    item_count: int = Field(ge=1, le=100)
    completed_item_count: int = Field(ge=0, le=100)
    links: RelativeLinks


class ExecutionDetail(ExecutionSummary):
    model_config = ConfigDict(extra="forbid")
    items: list[ExecutionItem] = Field(min_length=1, max_length=100)
    change_evidence: list[ChangeEventOutput] = Field(max_length=128)
    change_evidence_truncated: bool
    pinned_change_events: list[ChangeEventOutput] = Field(max_length=202)


class ExecutionPage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[ExecutionSummary] = Field(max_length=100)
    next_cursor: str | None = Field(default=None, min_length=1, max_length=2048)


class ExecutionListQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    limit: int = Field(default=50, ge=1, le=100)
    cursor: str | None = Field(default=None, min_length=1, max_length=2048)
    project_id: UUID | None = None
    environment_id: UUID | None = None
    test_case_id: UUID | None = None
    suite_id: UUID | None = None
    status: ExecutionStatus | None = None
    verdict: Verdict | None = None
    created_from: datetime | None = None
    created_before: datetime | None = None

    @field_validator("created_from", "created_before", mode="before")
    @classmethod
    def exact_input_timestamp(cls, value: object) -> object:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("timestamp must be UTC")
        try:
            parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)
        except ValueError:
            raise ValueError("timestamp must be UTC") from None
        if _timestamp(parsed) != value:
            raise ValueError("timestamp must be UTC")
        return parsed

    @model_validator(mode="after")
    def nonzero_uuid_filters(self) -> ExecutionListQuery:
        for value in (
            self.project_id,
            self.environment_id,
            self.test_case_id,
            self.suite_id,
        ):
            if value is not None and value.int == 0:
                raise ValueError("resource identifier is invalid")
        return self


def _filter_fingerprint(query: ExecutionListQuery) -> str:
    values = query.model_dump(mode="json", exclude={"cursor"})
    return hashlib.sha256(
        json.dumps(values, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _encode_cursor(after: tuple[datetime, UUID], fingerprint: str) -> str:
    payload = {
        "after": {"created_at": _timestamp(after[0]), "id": str(after[1])},
        "cursor_version": 1,
        "filter_fingerprint": fingerprint,
        "resource_kind": "executions",
        "scope_id": None,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, item in pairs:
        if key in result:
            raise ValueError
        result[key] = item
    return result


def _reject_constant(_: str) -> object:
    raise ValueError


def _decode_cursor(value: str, fingerprint: str) -> tuple[datetime, UUID]:
    try:
        if not _CURSOR_PATTERN.fullmatch(value):
            raise ValueError
        decoded = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
        if len(decoded) > 1536:
            raise ValueError
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
            raise ValueError
        if (
            payload["cursor_version"] != 1
            or payload["filter_fingerprint"] != fingerprint
            or payload["resource_kind"] != "executions"
            or payload["scope_id"] is not None
        ):
            raise ValueError
        after = payload["after"]
        if not isinstance(after, dict) or set(after) != {"created_at", "id"}:
            raise ValueError
        created_text = after["created_at"]
        id_text = after["id"]
        if not isinstance(created_text, str) or not isinstance(id_text, str):
            raise ValueError
        created_at = datetime.strptime(created_text, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)
        if _timestamp(created_at) != created_text:
            raise ValueError
        execution_id = UUID(id_text)
        if execution_id.int == 0 or str(execution_id) != id_text:
            raise ValueError
        return created_at, execution_id
    except (ValueError, TypeError, KeyError, UnicodeError, binascii.Error, json.JSONDecodeError):
        raise ValueError from None


def _summary(record: ExecutionRecord) -> ExecutionSummary:
    return ExecutionSummary(
        id=record.id,
        project_id=record.project_id,
        environment_id=record.environment_id,
        environment_revision_id=record.environment_revision_id,
        source_type=cast(Literal["test_case", "suite"], record.source_type),
        source_id=record.source_id,
        source_revision_id=record.source_revision_id,
        status=cast(ExecutionStatus, record.status),
        verdict=cast(Verdict | None, record.verdict),
        created_at=record.created_at,
        started_at=record.started_at,
        finished_at=record.finished_at,
        item_count=len(record.items),
        completed_item_count=record.completed_item_count,
        links=RelativeLinks(self=f"/api/v1/executions/{record.id}"),
    )


def _attempt_summary(attempt: AttemptRecord) -> AttemptSummary:
    return AttemptSummary(
        id=attempt.id,
        sequence=attempt.sequence,
        state=cast(AttemptState, attempt.state),
        verdict=cast(Verdict | None, attempt.verdict),
        created_at=attempt.created_at,
        dispatch_recorded_at=attempt.dispatch_recorded_at,
        response_recorded_at=attempt.response_recorded_at,
        finished_at=attempt.finished_at,
        duration_ms=attempt.duration_ms,
        dispatch_certainty=cast(DispatchCertainty, attempt.dispatch_certainty),
        transport_outcome=cast(TransportOutcome | None, attempt.transport_outcome),
        preparation_error_code=cast(PreparationErrorCode | None, attempt.preparation_error_code),
        redirect_rejection_code=cast(RedirectRejectionCode | None, attempt.redirect_rejection_code),
        primary_trace_id=attempt.primary_trace_id,
        client_span_id=attempt.client_span_id,
        replayed_by_attempt_id=attempt.replay_successor_id,
        included_in_verdict=attempt.included_in_verdict,
        links=RelativeLinks(self=f"/api/v1/attempts/{attempt.id}"),
    )


_SENSITIVE_RESPONSE_HEADERS = frozenset(
    {
        "authorization",
        "proxy-authorization",
        "cookie",
        "set-cookie",
        "location",
        "x-api-key",
        "x-api-key-secret",
    }
)


def _response_observation(
    artifact: ResponseArtifact | None, *, now: datetime
) -> tuple[ResponseObservation | None, ObservationState]:
    if artifact is None:
        return None, ObservationState.NOT_RECORDED
    if artifact.expires_at <= now:
        return None, ObservationState.EXPIRED

    safe_headers: list[ResponseHeader] = []
    aggregate_bytes = 0
    for raw_name, raw_value in sorted(artifact.headers.items()):
        if not isinstance(raw_name, str) or not isinstance(raw_value, str):
            continue
        name = raw_name.lower()
        value = "[REDACTED]" if name in _SENSITIVE_RESPONSE_HEADERS else raw_value[:8192]
        if not re.fullmatch(r"[!#$%&'*+.^_`|~0-9a-z-]+", name):
            continue
        if "\x00" in value or "\r" in value or "\n" in value:
            continue
        entry_bytes = len(name.encode()) + len(value.encode())
        if aggregate_bytes + entry_bytes > 32_768 or len(safe_headers) >= 64:
            break
        safe_headers.append(ResponseHeader(name=name, value=value))
        aggregate_bytes += entry_bytes

    body_kind: Literal["json", "text", "omitted"] = "omitted"
    body: str | None = None
    omitted = artifact.redaction_unavailable or artifact.body_kind not in {"json", "text"}
    conversion_failed = False
    if not omitted and artifact.body_content is not None:
        try:
            if artifact.body_kind == "json":
                body = canonical_json(artifact.body_content)
            elif isinstance(artifact.body_content, str):
                body = artifact.body_content
            else:
                omitted = True
        except (TypeError, ValueError):
            omitted = True
            conversion_failed = True
        if body is not None and len(body.encode("utf-8")) > 1_048_576:
            omitted = True
            conversion_failed = True
    if not omitted and body is not None:
        body_kind = "json" if artifact.body_kind == "json" else "text"
        state = ObservationState.AVAILABLE
    else:
        body = None
        state = ObservationState.OMITTED
    return (
        ResponseObservation(
            id=artifact.attempt_id,
            status_code=artifact.status_code,
            headers=safe_headers,
            body_kind=body_kind,
            body=body,
            captured_bytes=min(artifact.source_bytes_captured, 1_048_576),
            truncated=artifact.truncated,
            redaction_unavailable=artifact.redaction_unavailable or conversion_failed,
            recorded_at=artifact.recorded_at,
            expires_at=artifact.expires_at,
        ),
        state,
    )


def _trace_reference_output(
    record: TraceReferenceRecord, *, tempo_trace_url_template: str | None
) -> TraceReferenceOutput | None:
    try:
        evidence = (
            TraceEvidenceOutput.model_validate(record.evidence_json)
            if record.evidence_json is not None
            else None
        )
    except ValidationError:
        evidence = None
    try:
        return TraceReferenceOutput(
            id=record.id,
            relation=cast(Literal["primary", "linked"], record.relation),
            trace_id=record.trace_id,
            span_id=record.span_id,
            correlation_source=cast(
                Literal["sentinel_context", "baggage_attribute_search"], record.correlation_source
            ),
            status=cast(
                Literal[
                    "pending",
                    "missing",
                    "available",
                    "partial",
                    "tempo_unavailable",
                    "expired",
                ],
                record.status,
            ),
            first_checked_at=record.first_checked_at,
            last_checked_at=record.last_checked_at,
            deadline_at=record.deadline_at,
            lookup_attempt_count=record.lookup_attempt_count,
            last_error_code=cast(Any, record.last_error_code),
            evidence=evidence,
            tempo_url=(
                tempo_trace_url_template.replace("{trace_id}", record.trace_id)
                if tempo_trace_url_template is not None
                else None
            ),
        )
    except ValidationError:
        return None


def _attempt_detail(
    record: AttemptReadRecord, *, tempo_trace_url_template: str | None = None
) -> AttemptDetail:
    observation, observation_state = _response_observation(record.artifact, now=record.read_at)
    attempt = record.attempt
    if record.artifact is None and attempt.response_recorded_at is not None:
        observation_state = ObservationState.OMITTED
    summary = _attempt_summary(attempt)
    trace_references = sorted(
        getattr(record, "trace_references", ()),
        key=lambda reference: (
            reference.relation != "primary",
            reference.trace_id,
            str(reference.id),
        ),
    )
    return AttemptDetail(
        **summary.model_dump(),
        execution_id=record.execution_id,
        execution_item_id=attempt.execution_item_id,
        request_fingerprint=attempt.request_fingerprint,
        observation=observation,
        observation_state=observation_state,
        baseline_comparison=_comparison_output(getattr(record, "comparison", None)),
        evaluations=[_evaluation_output(value) for value in getattr(record, "evaluations", ())],
        evaluation_error_code=cast(
            Literal["platform_evaluation_failure"] | None,
            record.attempt.evaluation_error_code,
        ),
        baseline_promotion=_promotion_output(getattr(record, "promotion", None)),
        trace_references=[
            output
            for reference in trace_references[:17]
            if (
                output := _trace_reference_output(
                    reference, tempo_trace_url_template=tempo_trace_url_template
                )
            )
            is not None
        ],
        trace_references_truncated=(
            getattr(record, "trace_references_truncated", False) or len(trace_references) > 17
        ),
    )


def _comparison_output(value: ComparisonRead | None) -> BaselineComparisonOutput:
    if value is None:
        return BaselineComparisonOutput(
            state="not_evaluated",
            baseline_activation_id=None,
            baseline_id=None,
            baseline_version=None,
            policy_fingerprint=None,
            checked_at=None,
        )
    return BaselineComparisonOutput(
        state=cast(Any, value.state),
        baseline_activation_id=value.baseline_activation_id,
        baseline_id=value.baseline_id,
        baseline_version=value.baseline_version,
        policy_fingerprint=value.policy_fingerprint,
        checked_at=value.checked_at,
    )


def _evaluation_output(value: EvaluationRead) -> EvaluationOutput:
    return EvaluationOutput(
        id=value.id,
        ordinal=value.ordinal,
        kind=cast(Any, value.kind),
        rule_id=value.rule_id,
        severity=cast(Any, value.severity),
        outcome=cast(Any, value.outcome),
        message_code=cast(Any, value.message_code),
        expected=value.expected,
        actual=value.actual,
        evidence_omitted=value.evidence_omitted,
    )


def _promotion_output(value: PromotionRead | None) -> BaselinePromotionOutput:
    if value is None:
        return BaselinePromotionOutput(
            eligible=False,
            warning_codes=[],
            ineligibility_codes=["attempt_not_evaluated"],
        )
    return BaselinePromotionOutput(
        eligible=value.eligible,
        warning_codes=list(cast(Any, value.warning_codes)),
        ineligibility_codes=list(cast(Any, value.ineligibility_codes)),
    )


def _change_output(event: Any) -> ChangeEventOutput:
    return ChangeEventOutput(
        id=event.id,
        project_id=event.project_id,
        kind=event.kind.value,
        subject_type=event.subject_type.value,
        subject_id=event.subject_id,
        before_ref=event.before_ref,
        after_ref=event.after_ref,
        summary=ChangeEventSummary(
            changed_fields=[field.value for field in event.summary.changed_fields]
        ),
        created_at=event.created_at,
    )


def _detail(record: ExecutionRecord) -> ExecutionDetail:
    return ExecutionDetail(
        **_summary(record).model_dump(),
        items=[
            ExecutionItem(
                id=item.id,
                ordinal=item.ordinal,
                test_case_id=item.test_case_id,
                test_case_revision_id=item.test_case_revision_id,
                test_case_revision_version=item.test_case_revision_version,
                status=cast(ItemStatus, item.status),
                verdict=cast(Verdict | None, item.verdict),
                started_at=item.started_at,
                finished_at=item.finished_at,
                attempts=[_attempt_summary(attempt) for attempt in item.attempts],
                attempts_truncated=item.attempts_truncated,
                attempt_count=item.attempt_count,
            )
            for item in record.items
        ],
        change_evidence=[_change_output(event) for event in record.change_evidence.events],
        change_evidence_truncated=record.change_evidence.truncated,
        pinned_change_events=[_change_output(event) for event in record.pinned_change_events],
    )


def _validate_idempotency(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        encoded = value.encode("ascii")
    except UnicodeEncodeError:
        raise ValueError from None
    if not 1 <= len(encoded) <= 128 or _IDEMPOTENCY_PATTERN.fullmatch(value) is None:
        raise ValueError
    return value


def execution_router(service: PostgresExecutionService) -> APIRouter:
    router = APIRouter(prefix="/api/v1/executions", tags=["executions"])

    @router.post(
        "",
        response_model=ExecutionDetail,
        status_code=202,
        operation_id="create_execution",
        responses={202: {"headers": {"Location": _LOCATION_HEADER}}, **_PROBLEMS},
    )
    def create_execution(
        command: ExecutionCreate,
        response: Response,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> ExecutionDetail | Response:
        try:
            key = _validate_idempotency(idempotency_key)
        except ValueError:
            return field_problem(
                422,
                "validation_failed",
                "Request validation failed",
                location="header",
                pointer="/idempotency-key",
                field_code="value_invalid",
            )
        try:
            record = service.create(
                ExecutionCreateCommand(
                    environment_id=command.environment_id,
                    test_case_id=command.test_case_id,
                    suite_id=command.suite_id,
                ),
                idempotency_key=key,
            )
        except ExecutionResourceNotFound:
            return problem(404, "resource_not_found", "Request failed")
        except ExecutionIdempotencyConflict:
            return problem(409, "idempotency_conflict", "Idempotency conflict")
        except ExecutionValidationError:
            return problem(422, "validation_failed", "Request validation failed")
        except (ExecutionInfrastructureError, OperationalError, IntegrityError):
            return problem(500, "internal_error", "Internal server error")
        response.headers["Location"] = f"/api/v1/executions/{record.id}"
        return _detail(record)

    @router.get(
        "",
        response_model=ExecutionPage,
        operation_id="list_executions",
        responses={
            status: definition
            for status, definition in _PROBLEMS.items()
            if status not in {409, 413, 415}
        },
    )
    def list_executions(query: Annotated[ExecutionListQuery, Query()]) -> ExecutionPage | Response:
        if query.test_case_id is not None and query.suite_id is not None:
            return field_problem(
                422,
                "validation_failed",
                "Request validation failed",
                location="query",
                pointer="/suite_id",
                field_code="incompatible_fields",
            )
        if (
            query.created_from
            and query.created_before
            and query.created_from >= query.created_before
        ):
            return field_problem(
                422,
                "validation_failed",
                "Request validation failed",
                location="query",
                pointer="/created_before",
                field_code="value_invalid",
            )
        fingerprint = _filter_fingerprint(query)
        try:
            after = _decode_cursor(query.cursor, fingerprint) if query.cursor else None
        except ValueError:
            return field_problem(
                422,
                "validation_failed",
                "Request validation failed",
                location="query",
                pointer="/cursor",
                field_code="cursor_invalid",
            )
        try:
            page = service.list(
                limit=query.limit,
                after=after,
                project_id=query.project_id,
                environment_id=query.environment_id,
                test_case_id=query.test_case_id,
                suite_id=query.suite_id,
                status=query.status,
                verdict=query.verdict,
                created_from=query.created_from,
                created_before=query.created_before,
            )
        except ExecutionResourceNotFound:
            return problem(404, "resource_not_found", "Request failed")
        except ExecutionValidationError:
            return problem(422, "validation_failed", "Request validation failed")
        except ExecutionInfrastructureError:
            return problem(500, "internal_error", "Internal server error")
        return ExecutionPage(
            items=[_summary(record) for record in page.items],
            next_cursor=_encode_cursor(page.next_after, fingerprint) if page.next_after else None,
        )

    @router.get(
        "/{execution_id}",
        response_model=ExecutionDetail,
        operation_id="get_execution",
        responses=_PROBLEMS,
    )
    def get_execution(
        execution_id: Annotated[str, Path(pattern=_UUID_PATTERN)],
    ) -> ExecutionDetail | Response:
        parsed = UUID(execution_id)
        if parsed.int == 0 or str(parsed) != execution_id:
            return field_problem(
                422,
                "validation_failed",
                "Request validation failed",
                location="path",
                pointer="/execution_id",
                field_code="invalid_uuid",
            )
        record = service.get(parsed)
        if record is None:
            return problem(404, "resource_not_found", "Request failed")
        return _detail(record)

    return router


def attempt_router(
    service: PostgresExecutionService, *, tempo_trace_url_template: str | None = None
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/attempts", tags=["attempts"])

    @router.get(
        "/{attempt_id}",
        response_model=AttemptDetail,
        operation_id="get_attempt",
        responses=_PROBLEMS,
    )
    def get_attempt(
        attempt_id: Annotated[str, Path(pattern=_UUID_PATTERN)],
    ) -> AttemptDetail | Response:
        parsed = UUID(attempt_id)
        if parsed.int == 0 or str(parsed) != attempt_id:
            return field_problem(
                422,
                "validation_failed",
                "Request validation failed",
                location="path",
                pointer="/attempt_id",
                field_code="invalid_uuid",
            )
        record = service.get_attempt(parsed)
        if record is None:
            return problem(404, "resource_not_found", "Request failed")
        return _attempt_detail(record, tempo_trace_url_template=tempo_trace_url_template)

    return router

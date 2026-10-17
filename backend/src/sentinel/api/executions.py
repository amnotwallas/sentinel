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
    field_serializer,
    field_validator,
    model_validator,
)
from pydantic.json_schema import SkipJsonSchema
from sqlalchemy.exc import IntegrityError, OperationalError

from sentinel.api.problems import Problem, field_problem, problem
from sentinel.execution.creation import (
    ExecutionCreateCommand,
    ExecutionIdempotencyConflict,
    ExecutionInfrastructureError,
    ExecutionRecord,
    ExecutionResourceNotFound,
    ExecutionValidationError,
    PostgresExecutionService,
)

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
    duration_ms: int | None = Field(default=None, ge=0)
    dispatch_certainty: DispatchCertainty
    transport_outcome: TransportOutcome | None
    preparation_error_code: PreparationErrorCode | None
    redirect_rejection_code: RedirectRejectionCode | None
    primary_trace_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")
    client_span_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{16}$")
    replayed_by_attempt_id: UUID | None
    included_in_verdict: bool
    links: RelativeLinks


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
                attempts=[],
                attempts_truncated=False,
                attempt_count=0,
            )
            for item in record.items
        ],
        change_evidence=[],
        change_evidence_truncated=False,
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

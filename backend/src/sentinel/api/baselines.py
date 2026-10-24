from __future__ import annotations

import base64
import binascii
import json
import re
from datetime import datetime
from typing import Annotated, Any, Literal, cast
from uuid import UUID

from fastapi import APIRouter, Header, Path, Query, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from sentinel.api.executions import _PROBLEMS, TimestampModel
from sentinel.api.problems import Problem, field_problem, problem
from sentinel.regression.baselines import (
    ActivationSummary as DomainActivationSummary,
)
from sentinel.regression.baselines import (
    BaselineConfirmationRequired,
    BaselineIncompatible,
    BaselineIneligible,
    BaselineNotFound,
    BaselineResourceConflict,
    BaselineRevisionConflict,
    BaselineScope,
    BaselineService,
    BaselineValidationError,
)
from sentinel.regression.baselines import (
    BaselineSummary as DomainBaselineSummary,
)

_UUID_PATTERN = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
_CURSOR_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,2048}$")
_ETAG_PATTERN = re.compile(r'^"[^"]+"$')
_BASELINE_PROBLEMS = {
    **_PROBLEMS,
    428: {
        "model": Problem,
        "description": "RFC 9457 problem response",
        "content": {"application/problem+json": {}},
    },
}
PromotionWarning = Literal[
    "missing_baseline", "incompatible_baseline", "observed_change", "performance_warning"
]
PromotionIneligibility = Literal[
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


class BaselineLinks(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_attempt: str = Field(pattern=r"^/api/v1/attempts/[0-9a-f-]+$")
    test_case: str = Field(pattern=r"^/api/v1/test-cases/[0-9a-f-]+$")


class BaselineSummary(TimestampModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    test_case_id: UUID
    environment_id: UUID
    version: int = Field(ge=1)
    source_attempt_id: UUID
    source_execution_id: UUID
    source_test_case_revision_id: UUID
    source_attempt_verdict: Literal[
        "passed",
        "functional_regression",
        "performance_warning",
        "observed_change",
        "inconclusive",
        "baseline_required",
        "not_evaluated",
    ]
    source_finished_at: datetime
    policy_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_at: datetime
    reason: str | None = Field(max_length=500)
    active: bool
    activated_at: datetime | None
    links: BaselineLinks


class BaselineActivationSummary(TimestampModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    test_case_id: UUID
    environment_id: UUID
    baseline_id: UUID
    baseline_version: int = Field(ge=1)
    activated_at: datetime
    deactivated_at: datetime | None
    reason: str | None = Field(max_length=500)


class BaselineCreateResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    baseline: BaselineSummary
    activation: BaselineActivationSummary


class BaselinePage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[BaselineSummary] = Field(max_length=100)
    next_cursor: str | None = Field(min_length=1, max_length=2048)


class BaselinePromotionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    environment_id: UUID
    source_attempt_id: UUID
    reason: str | None
    confirmation: str = Field(json_schema_extra={"const": "promote_selected_values"})
    acknowledged_warnings: list[PromotionWarning] = Field(max_length=4)


class BaselineActivationBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    environment_id: UUID
    baseline_id: UUID
    reason: str | None


def _cursor_encode(test_case_id: UUID, environment_id: UUID, after: tuple[int, UUID]) -> str:
    payload = {
        "after": {"version": after[0], "id": str(after[1])},
        "cursor_version": 1,
        "environment_id": str(environment_id),
        "resource_kind": "baselines",
        "test_case_id": str(test_case_id),
    }
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _cursor_decode(value: str, test_case_id: UUID, environment_id: UUID) -> tuple[int, UUID]:
    try:
        if not _CURSOR_PATTERN.fullmatch(value):
            raise ValueError
        raw = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
        if len(raw) > 1536:
            raise ValueError
        payload = json.loads(
            raw.decode(), object_pairs_hook=_unique_object, parse_constant=_reject_constant
        )
        if set(payload) != {
            "after",
            "cursor_version",
            "environment_id",
            "resource_kind",
            "test_case_id",
        }:
            raise ValueError
        if payload["cursor_version"] != 1 or payload["resource_kind"] != "baselines":
            raise ValueError
        if payload["test_case_id"] != str(test_case_id) or payload["environment_id"] != str(
            environment_id
        ):
            raise ValueError
        after = payload["after"]
        if set(after) != {"version", "id"} or not isinstance(after["version"], int):
            raise ValueError
        baseline_id = UUID(after["id"])
        if str(baseline_id) != after["id"] or after["version"] < 1:
            raise ValueError
        return after["version"], baseline_id
    except (
        ValueError,
        TypeError,
        KeyError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        binascii.Error,
    ):
        raise ValueError from None


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError
        result[key] = value
    return result


def _reject_constant(_: str) -> object:
    raise ValueError


def _etag(value: str | None) -> str | None:
    if value is None:
        return None
    if not _ETAG_PATTERN.fullmatch(value) or value.startswith('"*') or value.startswith('"W/'):
        return None
    return value


def _baseline(value: DomainBaselineSummary) -> BaselineSummary:
    baseline = value
    return BaselineSummary(
        id=baseline.id,
        test_case_id=baseline.test_case_id,
        environment_id=baseline.environment_id,
        version=baseline.version,
        source_attempt_id=baseline.source_attempt_id,
        source_execution_id=baseline.source_execution_id,
        source_test_case_revision_id=baseline.source_test_case_revision_id,
        source_attempt_verdict=cast(Any, baseline.source_attempt_verdict),
        source_finished_at=baseline.source_finished_at,
        policy_fingerprint=baseline.policy_fingerprint,
        created_at=baseline.created_at,
        reason=baseline.reason,
        active=baseline.active,
        activated_at=baseline.activated_at,
        links=BaselineLinks(
            source_attempt=f"/api/v1/attempts/{baseline.source_attempt_id}",
            test_case=f"/api/v1/test-cases/{baseline.test_case_id}",
        ),
    )


def _activation(value: DomainActivationSummary) -> BaselineActivationSummary:
    return BaselineActivationSummary(
        id=value.id,
        test_case_id=value.test_case_id,
        environment_id=value.environment_id,
        baseline_id=value.baseline_id,
        baseline_version=value.baseline_version,
        activated_at=value.activated_at,
        deactivated_at=value.deactivated_at,
        reason=value.reason,
    )


def _problem_for(error: Exception) -> JSONResponse:
    if isinstance(error, BaselineNotFound):
        return problem(404, "resource_not_found", "Request failed")
    if isinstance(error, BaselineRevisionConflict):
        return problem(412, "revision_conflict", "Revision conflict")
    if isinstance(error, BaselineResourceConflict):
        return problem(409, "resource_conflict", "Resource conflict")
    if isinstance(error, BaselineIneligible):
        return problem(409, "baseline_ineligible", "Baseline ineligible")
    if isinstance(error, BaselineIncompatible):
        return problem(409, "baseline_incompatible", "Baseline incompatible")
    if isinstance(error, BaselineConfirmationRequired):
        return problem(409, "baseline_confirmation_required", "Baseline confirmation required")
    return problem(422, "validation_failed", "Request validation failed")


def _precondition(value: str | None) -> str | JSONResponse:
    if value is None:
        return problem(428, "revision_precondition_required", "Revision precondition required")
    if _etag(value) is None:
        return field_problem(
            422,
            "validation_failed",
            "Request validation failed",
            location="header",
            pointer="/if-match",
            field_code="value_invalid",
        )
    return value


def baseline_router(service: BaselineService) -> APIRouter:
    router = APIRouter(prefix="/api/v1/test-cases", tags=["baselines"])

    @router.get(
        "/{test_case_id}/baselines",
        response_model=BaselinePage,
        operation_id="list_baselines",
        responses={
            200: {"headers": {"ETag": {"schema": {"type": "string"}}}},
            **_BASELINE_PROBLEMS,
        },
    )
    def list_baselines(
        test_case_id: Annotated[str, Path(pattern=_UUID_PATTERN)],
        response: Response,
        environment_id: Annotated[UUID, Query()],
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        cursor: Annotated[str | None, Query(min_length=1, max_length=2048)] = None,
    ) -> BaselinePage | JSONResponse:
        try:
            parsed_test_case = UUID(test_case_id)
            after = _cursor_decode(cursor, parsed_test_case, environment_id) if cursor else None
            page = service.list_history(
                BaselineScope(parsed_test_case, environment_id), after=after, limit=limit
            )
        except (ValueError, BaselineValidationError):
            return _problem_for(BaselineValidationError())
        except BaselineNotFound:
            return _problem_for(BaselineNotFound())
        response.headers["ETag"] = page.etag
        return BaselinePage(
            items=[_baseline(item) for item in page.items],
            next_cursor=(
                _cursor_encode(parsed_test_case, environment_id, page.next_after)
                if page.next_after
                else None
            ),
        )

    @router.post(
        "/{test_case_id}/baselines",
        response_model=BaselineCreateResult,
        operation_id="promote_baseline",
        status_code=201,
        responses={
            200: {
                "model": BaselineCreateResult,
                "headers": {"ETag": {"schema": {"type": "string"}}},
            },
            201: {"headers": {"ETag": {"schema": {"type": "string"}}}},
            **_BASELINE_PROBLEMS,
        },
    )
    def promote_baseline(
        test_case_id: Annotated[str, Path(pattern=_UUID_PATTERN)],
        body: BaselinePromotionBody,
        response: Response,
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> BaselineCreateResult | JSONResponse:
        precondition = _precondition(if_match)
        if not isinstance(precondition, str):
            return precondition
        try:
            result = service.promote(
                BaselineScope(UUID(test_case_id), body.environment_id),
                source_attempt_id=body.source_attempt_id,
                reason=body.reason,
                confirmation=body.confirmation,
                acknowledged_warnings=body.acknowledged_warnings,
                if_match=precondition,
            )
        except (
            BaselineNotFound,
            BaselineRevisionConflict,
            BaselineResourceConflict,
            BaselineIneligible,
            BaselineIncompatible,
            BaselineConfirmationRequired,
            BaselineValidationError,
        ) as error:
            return _problem_for(error)
        response.status_code = 201 if result.created else 200
        response.headers["ETag"] = result.etag
        return BaselineCreateResult(
            baseline=_baseline(result.baseline), activation=_activation(result.activation)
        )

    @router.post(
        "/{test_case_id}/baseline-activations",
        response_model=BaselineActivationSummary,
        operation_id="activate_baseline",
        status_code=201,
        responses={
            200: {
                "model": BaselineActivationSummary,
                "headers": {"ETag": {"schema": {"type": "string"}}},
            },
            201: {"headers": {"ETag": {"schema": {"type": "string"}}}},
            **_BASELINE_PROBLEMS,
        },
    )
    def activate_baseline(
        test_case_id: Annotated[str, Path(pattern=_UUID_PATTERN)],
        body: BaselineActivationBody,
        response: Response,
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> BaselineActivationSummary | JSONResponse:
        precondition = _precondition(if_match)
        if not isinstance(precondition, str):
            return precondition
        try:
            result = service.activate(
                BaselineScope(UUID(test_case_id), body.environment_id),
                baseline_id=body.baseline_id,
                reason=body.reason,
                if_match=precondition,
            )
        except (
            BaselineNotFound,
            BaselineRevisionConflict,
            BaselineResourceConflict,
            BaselineIneligible,
            BaselineIncompatible,
            BaselineConfirmationRequired,
            BaselineValidationError,
        ) as error:
            return _problem_for(error)
        response.status_code = 201 if result.created else 200
        response.headers["ETag"] = result.etag
        return _activation(result.activation)

    return router

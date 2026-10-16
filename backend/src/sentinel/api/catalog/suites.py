from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Header, Path, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_serializer

from sentinel.api.catalog.pagination import (
    CursorInvalid,
    decode_suite_cursor,
    encode_suite_cursor,
)
from sentinel.api.problems import Problem, field_problem, problem
from sentinel.catalog.projects import ProjectNotFound, ProjectValidationError
from sentinel.catalog.suites import (
    Suite as DomainSuite,
)
from sentinel.catalog.suites import (
    SuiteNotFound,
    SuiteReferenceNotFound,
    SuiteRevisionConflict,
    SuiteService,
    SuiteValidationError,
    SuiteVersionExhausted,
)
from sentinel.catalog.suites import SuiteRevision as DomainSuiteRevision
from sentinel.catalog.suites import SuiteRevisionItem as DomainSuiteRevisionItem

_UUID_PATTERN = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
_ETAG_PATTERN = re.compile(
    rf'^"((?:project|environment|test_case|suite)):({_UUID_PATTERN[1:-1]}):([1-9][0-9]*)"$'
)
_PROBLEMS: dict[int | str, dict[str, Any]] = {
    status: {
        "model": Problem,
        "description": "RFC 9457 problem response",
        "content": {"application/problem+json": {}},
    }
    for status in (401, 403, 404, 409, 412, 413, 415, 422, 428, 500)
}
_ETAG_HEADER: dict[str, Any] = {
    "schema": {"type": "string"},
    "description": "Strong resource ETag",
}
_LOCATION_HEADER: dict[str, Any] = {
    "schema": {"type": "string"},
    "description": "Created resource path",
}


class SuiteWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)
    test_case_revision_ids: list[UUID] = Field(
        min_length=1,
        max_length=100,
        json_schema_extra={"uniqueItems": True},
    )


class SuiteRevisionItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ordinal: int = Field(ge=0, le=99)
    test_case_id: UUID
    test_case_revision_id: UUID
    test_case_revision_version: int = Field(ge=1, le=2_147_483_647)

    @field_serializer("test_case_id", "test_case_revision_id")
    def serialize_uuid(self, value: UUID) -> str:
        return str(value)


class SuiteRevision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID
    suite_id: UUID
    version: int = Field(ge=1, le=2_147_483_647)
    schema_version: Literal[1]
    items: list[SuiteRevisionItem] = Field(min_length=1, max_length=100)
    created_at: datetime

    @field_serializer("id", "suite_id")
    def serialize_uuid(self, value: UUID) -> str:
        return str(value)

    @field_serializer("created_at")
    def serialize_created_at(self, value: datetime) -> str:
        return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class SuiteDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID
    project_id: UUID
    name: str
    active_revision_id: UUID
    created_at: datetime
    updated_at: datetime
    active_revision: SuiteRevision

    @field_serializer("id", "project_id", "active_revision_id")
    def serialize_uuid(self, value: UUID) -> str:
        return str(value)

    @field_serializer("created_at", "updated_at")
    def serialize_time(self, value: datetime) -> str:
        return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class SuiteSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID
    project_id: UUID
    name: str
    active_revision_id: UUID
    created_at: datetime
    updated_at: datetime
    active_revision_version: int = Field(ge=1, le=2_147_483_647)

    @field_serializer("id", "project_id", "active_revision_id")
    def serialize_uuid(self, value: UUID) -> str:
        return str(value)

    @field_serializer("created_at", "updated_at")
    def serialize_time(self, value: datetime) -> str:
        return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class SuitePage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[SuiteSummary] = Field(max_length=100)
    next_cursor: str | None = Field(min_length=1, max_length=2048)


class ListQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    limit: int = Field(default=50, ge=1, le=100)
    cursor: str | None = Field(default=None, min_length=1, max_length=2048)


class EmptyQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _encoded_model(model: BaseModel) -> bytes:
    from sentinel.regression.policy import canonical_json

    return canonical_json(model.model_dump(mode="python")).encode("utf-8")


def _model_response(
    model: BaseModel,
    *,
    status_code: int = 200,
    headers: dict[str, str] | None = None,
) -> Response:
    return Response(
        content=_encoded_model(model),
        status_code=status_code,
        headers=headers,
        media_type="application/json",
    )


def _uuid(value: str) -> UUID | None:
    try:
        parsed = UUID(value)
    except ValueError:
        return None
    return parsed if parsed.int != 0 and str(parsed) == value else None


def _etag(suite: DomainSuite) -> str:
    return f'"suite:{suite.id}:{suite.state_version}"'


def _parse_if_match(value: str | None, suite_id: UUID) -> int | Response:
    if value is None:
        return problem(428, "revision_precondition_required", "Revision precondition required")
    match = _ETAG_PATTERN.fullmatch(value)
    if match is None:
        return field_problem(
            422,
            "validation_failed",
            "Request validation failed",
            location="header",
            pointer="/if-match",
            field_code="value_invalid",
        )
    resource_kind, raw_id, raw_version = match.groups()
    resource_id = _uuid(raw_id)
    try:
        version = int(raw_version)
    except ValueError:
        version = 0
    if resource_id is None or version > 2_147_483_647:
        return field_problem(
            422,
            "validation_failed",
            "Request validation failed",
            location="header",
            pointer="/if-match",
            field_code="value_invalid",
        )
    if resource_kind != "suite" or resource_id != suite_id:
        return problem(412, "revision_conflict", "Revision conflict")
    return version


def _invalid(location: str, pointer: str, code: str) -> Response:
    return field_problem(
        422,
        "validation_failed",
        "Request validation failed",
        location=location,
        pointer=pointer,
        field_code=code,
    )


def _item(item: DomainSuiteRevisionItem) -> SuiteRevisionItem:
    return SuiteRevisionItem(
        ordinal=item.ordinal,
        test_case_id=item.test_case_id,
        test_case_revision_id=item.test_case_revision_id,
        test_case_revision_version=item.test_case_revision_version,
    )


def _revision(revision: DomainSuiteRevision) -> SuiteRevision:
    return SuiteRevision(
        id=revision.id,
        suite_id=revision.suite_id,
        version=revision.version,
        schema_version=1,
        items=[_item(item) for item in revision.items],
        created_at=revision.created_at,
    )


def _detail(suite: DomainSuite) -> SuiteDetail:
    return SuiteDetail(
        id=suite.id,
        project_id=suite.project_id,
        name=suite.name,
        active_revision_id=suite.active_revision_id,
        created_at=suite.created_at,
        updated_at=suite.updated_at,
        active_revision=_revision(suite.active_revision),
    )


def _summary(suite: DomainSuite) -> SuiteSummary:
    return SuiteSummary(
        id=suite.id,
        project_id=suite.project_id,
        name=suite.name,
        active_revision_id=suite.active_revision_id,
        created_at=suite.created_at,
        updated_at=suite.updated_at,
        active_revision_version=suite.active_revision.version,
    )


def suite_router(service: SuiteService) -> APIRouter:
    router = APIRouter(tags=["catalog"])

    @router.post(
        "/api/v1/projects/{project_id}/suites",
        response_model=SuiteDetail,
        status_code=201,
        operation_id="create_suite",
        responses={
            201: {"headers": {"ETag": _ETAG_HEADER, "Location": _LOCATION_HEADER}},
            **_PROBLEMS,
        },
    )
    def create_suite(
        project_id: Annotated[str, Path(pattern=_UUID_PATTERN)],
        command: SuiteWrite,
        request: Request,
        query: Annotated[EmptyQuery, Query()],
    ) -> Response:
        if request.headers.get("if-match") is not None:
            return _invalid("header", "/if-match", "incompatible_fields")
        parsed_id = _uuid(project_id)
        if parsed_id is None:
            return _invalid("path", "/project_id", "invalid_uuid")
        try:
            suite = service.create(
                parsed_id,
                name=command.name,
                test_case_revision_ids=command.test_case_revision_ids,
            )
        except ProjectNotFound:
            return problem(404, "resource_not_found", "Request failed")
        except SuiteReferenceNotFound:
            return problem(404, "resource_not_found", "Request failed")
        except SuiteValidationError as error:
            return _invalid(
                "body",
                "/test_case_revision_ids",
                "duplicate" if "only once" in str(error) else "value_invalid",
            )
        except ProjectValidationError:
            return _invalid("body", "/name", "value_invalid")
        return _model_response(
            _detail(suite),
            status_code=201,
            headers={
                "Location": f"/api/v1/suites/{suite.id}",
                "ETag": _etag(suite),
            },
        )

    @router.get(
        "/api/v1/projects/{project_id}/suites",
        response_model=SuitePage,
        operation_id="list_suites",
        responses={k: v for k, v in _PROBLEMS.items() if k in {401, 403, 404, 422, 500}},
    )
    def list_suites(
        project_id: Annotated[str, Path(pattern=_UUID_PATTERN)],
        query: Annotated[ListQuery, Query()],
    ) -> SuitePage | Response:
        parsed_id = _uuid(project_id)
        if parsed_id is None:
            return _invalid("path", "/project_id", "invalid_uuid")
        try:
            after = decode_suite_cursor(parsed_id, query.cursor) if query.cursor else None
            page = service.list(parsed_id, limit=query.limit, after=after)
        except CursorInvalid:
            return _invalid("query", "/cursor", "cursor_invalid")
        except ProjectNotFound:
            return problem(404, "resource_not_found", "Request failed")
        return SuitePage(
            items=[_summary(item) for item in page.items],
            next_cursor=(
                encode_suite_cursor(parsed_id, page.next_after) if page.next_after else None
            ),
        )

    @router.get(
        "/api/v1/suites/{suite_id}",
        response_model=SuiteDetail,
        operation_id="get_suite",
        responses={200: {"headers": {"ETag": _ETAG_HEADER}}, **_PROBLEMS},
    )
    def get_suite(
        suite_id: Annotated[str, Path(pattern=_UUID_PATTERN)],
        query: Annotated[EmptyQuery, Query()],
    ) -> Response:
        parsed_id = _uuid(suite_id)
        if parsed_id is None:
            return _invalid("path", "/suite_id", "invalid_uuid")
        try:
            suite = service.get(parsed_id)
        except SuiteNotFound:
            return problem(404, "resource_not_found", "Request failed")
        return _model_response(_detail(suite), headers={"ETag": _etag(suite)})

    @router.put(
        "/api/v1/suites/{suite_id}",
        response_model=SuiteDetail,
        operation_id="revise_suite",
        responses={200: {"headers": {"ETag": _ETAG_HEADER}}, **_PROBLEMS},
    )
    def revise_suite(
        suite_id: Annotated[str, Path(pattern=_UUID_PATTERN)],
        command: SuiteWrite,
        query: Annotated[EmptyQuery, Query()],
        if_match: Annotated[str | None, Header()] = None,
    ) -> Response:
        parsed_id = _uuid(suite_id)
        if parsed_id is None:
            return _invalid("path", "/suite_id", "invalid_uuid")
        expected = _parse_if_match(if_match, parsed_id)
        if not isinstance(expected, int):
            return expected
        try:
            suite = service.update(
                parsed_id,
                expected_state_version=expected,
                name=command.name,
                test_case_revision_ids=command.test_case_revision_ids,
            )
        except SuiteNotFound:
            return problem(404, "resource_not_found", "Request failed")
        except SuiteReferenceNotFound:
            return problem(404, "resource_not_found", "Request failed")
        except SuiteRevisionConflict:
            return problem(412, "revision_conflict", "Revision conflict")
        except SuiteVersionExhausted:
            return problem(409, "resource_conflict", "Resource conflict")
        except SuiteValidationError as error:
            return _invalid(
                "body",
                "/test_case_revision_ids",
                "duplicate" if "only once" in str(error) else "value_invalid",
            )
        except ProjectValidationError:
            return _invalid("body", "/name", "value_invalid")
        return _model_response(_detail(suite), headers={"ETag": _etag(suite)})

    return router

import re
from datetime import UTC, datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Header, Path, Query, Request, Response
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

from sentinel.api.body_limit import PARSED_JSON_SCOPE_KEY
from sentinel.api.catalog.pagination import (
    CursorInvalid,
    decode_test_case_cursor,
    decode_test_case_revision_cursor,
    encode_test_case_cursor,
    encode_test_case_revision_cursor,
)
from sentinel.api.problems import Problem, field_problem, problem
from sentinel.catalog.definitions import DefinitionValidationError
from sentinel.catalog.projects import (
    ProjectNotFound,
    ProjectValidationError,
    normalize_project_name,
)
from sentinel.catalog.test_cases import (
    TestCase as DomainTestCase,
)
from sentinel.catalog.test_cases import (
    TestCaseNotFound,
    TestCaseRevisionConflict,
    TestCaseService,
    TestCaseValidationError,
    TestCaseVersionExhausted,
)
from sentinel.catalog.test_cases import TestCaseRevision as DomainTestCaseRevision
from sentinel.regression.policy import canonical_json

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
_MAX_CATALOG_RESPONSE_BYTES = 1_048_576


class ExactJSONRoute(APIRoute):
    def get_route_handler(self) -> Any:
        handler = super().get_route_handler()

        async def exact_json_handler(request: Request) -> Response:
            parsed = request.scope.get("state", {}).get(PARSED_JSON_SCOPE_KEY)
            if parsed is not None:
                # Starlette's Request.json() uses this cache. The body middleware
                # populated it with Decimal values from the original JSON tokens.
                request._json = parsed
            return await handler(request)

        return exact_json_handler


def _encoded_model(model: BaseModel) -> bytes:
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


class TestCaseWrite(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    name: str = Field(min_length=1, max_length=120)
    definition: dict[str, object]
    unsafe_replay_acknowledgement: Literal["duplicate_effects_possible"] | None = None

    @field_validator("name", mode="before")
    @classmethod
    def valid_name(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        try:
            return normalize_project_name(value)
        except ProjectValidationError:
            raise ValueError("invalid test case name") from None


class TestCaseRevision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID
    test_case_id: UUID
    version: int = Field(ge=1)
    schema_version: Literal[1]
    definition: dict[str, object]
    policy_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    unsafe_replay_acknowledged_at: datetime | None
    created_at: datetime

    @field_serializer("id", "test_case_id")
    def serialize_uuid(self, value: UUID) -> str:
        return str(value)

    @field_serializer("unsafe_replay_acknowledged_at")
    def serialize_acknowledged_at(self, value: datetime | None) -> str | None:
        return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ") if value else None

    @field_serializer("created_at")
    def serialize_created_at(self, value: datetime) -> str:
        return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class TestCaseDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID
    project_id: UUID
    name: str
    active_revision_id: UUID
    created_at: datetime
    updated_at: datetime
    active_revision: TestCaseRevision

    @field_serializer("id", "project_id", "active_revision_id")
    def serialize_uuid(self, value: UUID) -> str:
        return str(value)

    @field_serializer("created_at", "updated_at")
    def serialize_time(self, value: datetime) -> str:
        return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class TestCaseSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID
    project_id: UUID
    name: str
    active_revision_id: UUID
    created_at: datetime
    updated_at: datetime
    active_revision_version: int = Field(ge=1)

    @field_serializer("id", "project_id", "active_revision_id")
    def serialize_uuid(self, value: UUID) -> str:
        return str(value)

    @field_serializer("created_at", "updated_at")
    def serialize_time(self, value: datetime) -> str:
        return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class TestCasePage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[TestCaseSummary] = Field(max_length=100)
    next_cursor: str | None = Field(min_length=1, max_length=2048)


class TestCaseRevisionPage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[TestCaseRevision] = Field(max_length=100)
    next_cursor: str | None = Field(min_length=1, max_length=2048)


class ListQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    limit: int = Field(default=50, ge=1, le=100)
    cursor: str | None = Field(default=None, min_length=1, max_length=2048)


class EmptyQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _uuid(value: str) -> UUID | None:
    try:
        parsed = UUID(value)
    except ValueError:
        return None
    return parsed if parsed.int != 0 and str(parsed) == value else None


def _etag(test_case: DomainTestCase) -> str:
    return f'"test_case:{test_case.id}:{test_case.state_version}"'


def _revision(revision: DomainTestCaseRevision) -> TestCaseRevision:
    return TestCaseRevision(
        id=revision.id,
        test_case_id=revision.test_case_id,
        version=revision.version,
        schema_version=1,
        definition=revision.definition.to_document(),
        policy_fingerprint=revision.definition.policy_fingerprint,
        unsafe_replay_acknowledged_at=revision.unsafe_replay_acknowledged_at,
        created_at=revision.created_at,
    )


def _detail(test_case: DomainTestCase) -> TestCaseDetail:
    return TestCaseDetail(
        id=test_case.id,
        project_id=test_case.project_id,
        name=test_case.name,
        active_revision_id=test_case.active_revision_id,
        created_at=test_case.created_at,
        updated_at=test_case.updated_at,
        active_revision=_revision(test_case.active_revision),
    )


def _summary(test_case: DomainTestCase) -> TestCaseSummary:
    return TestCaseSummary(
        id=test_case.id,
        project_id=test_case.project_id,
        name=test_case.name,
        active_revision_id=test_case.active_revision_id,
        created_at=test_case.created_at,
        updated_at=test_case.updated_at,
        active_revision_version=test_case.active_revision.version,
    )


def _revision_page(
    test_case_id: UUID,
    revisions: list[DomainTestCaseRevision],
    next_after: tuple[int, UUID] | None,
) -> TestCaseRevisionPage:
    items = [_revision(item) for item in revisions]
    next_cursor = encode_test_case_revision_cursor(test_case_id, next_after) if next_after else None
    page = TestCaseRevisionPage(items=items, next_cursor=next_cursor)
    if len(_encoded_model(page)) <= _MAX_CATALOG_RESPONSE_BYTES:
        return page
    for count in range(len(items) - 1, 0, -1):
        last = revisions[count - 1]
        page = TestCaseRevisionPage(
            items=items[:count],
            next_cursor=encode_test_case_revision_cursor(test_case_id, (last.version, last.id)),
        )
        if len(_encoded_model(page)) <= _MAX_CATALOG_RESPONSE_BYTES:
            return page
    return TestCaseRevisionPage(items=items[:1], next_cursor=next_cursor)


def _definition_error(error: DefinitionValidationError) -> Response:
    allowed = {
        "type_invalid",
        "value_invalid",
        "extra_field",
        "limit_exceeded",
        "duplicate",
        "invalid_uuid",
        "invalid_json_pointer",
        "invalid_secret_reference",
        "secret_placement_forbidden",
        "credential_literal_forbidden",
        "trace_context_forbidden",
        "incompatible_fields",
    }
    code = error.code if error.code in allowed else "value_invalid"
    secret_error = code in {"invalid_secret_reference", "secret_placement_forbidden"}
    return field_problem(
        422,
        "secret_reference_invalid" if secret_error else "validation_failed",
        "Secret reference invalid" if secret_error else "Request validation failed",
        location="body",
        pointer="/definition",
        field_code=code,
    )


def _parse_if_match(value: str | None, test_case_id: UUID) -> int | Response:
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
    resource_kind, raw_id, raw = match.groups()
    try:
        parsed = int(raw)
    except ValueError:
        parsed = 0
    resource_id = _uuid(raw_id)
    if resource_id is None or parsed > 2_147_483_647:
        return field_problem(
            422,
            "validation_failed",
            "Request validation failed",
            location="header",
            pointer="/if-match",
            field_code="value_invalid",
        )
    if resource_kind != "test_case" or resource_id != test_case_id:
        return problem(412, "revision_conflict", "Revision conflict")
    return parsed


def _invalid(location: str, pointer: str, code: str) -> Response:
    return field_problem(
        422,
        "validation_failed",
        "Request validation failed",
        location=location,
        pointer=pointer,
        field_code=code,
    )


def test_case_router(service: TestCaseService) -> APIRouter:
    router = APIRouter(tags=["catalog"], route_class=ExactJSONRoute)

    @router.post(
        "/api/v1/projects/{project_id}/test-cases",
        response_model=TestCaseDetail,
        status_code=201,
        operation_id="create_test_case",
        responses={
            201: {"headers": {"ETag": _ETAG_HEADER, "Location": _LOCATION_HEADER}},
            **_PROBLEMS,
        },
    )
    def create_test_case(
        project_id: Annotated[str, Path(pattern=_UUID_PATTERN)],
        command: TestCaseWrite,
        request: Request,
        query: Annotated[EmptyQuery, Query()],
    ) -> Response:
        if request.headers.get("if-match") is not None:
            return _invalid("header", "/if-match", "incompatible_fields")
        parsed_id = _uuid(project_id)
        if parsed_id is None:
            return _invalid("path", "/project_id", "invalid_uuid")
        try:
            test_case = service.create(
                parsed_id,
                name=command.name,
                definition=command.definition,
                unsafe_replay_acknowledgement=command.unsafe_replay_acknowledgement,
            )
        except ProjectNotFound:
            return problem(404, "resource_not_found", "Request failed")
        except DefinitionValidationError as error:
            return _definition_error(error)
        except (TestCaseValidationError, ProjectValidationError) as error:
            if "acknowledgement" in str(error):
                return _invalid(
                    "body",
                    "/unsafe_replay_acknowledgement",
                    (
                        "incompatible_fields"
                        if "incompatible" in str(error)
                        else "unsafe_replay_acknowledgement_required"
                    ),
                )
            return _invalid("body", "/name", "value_invalid")
        return _model_response(
            _detail(test_case),
            status_code=201,
            headers={
                "Location": f"/api/v1/test-cases/{test_case.id}",
                "ETag": _etag(test_case),
            },
        )

    @router.get(
        "/api/v1/projects/{project_id}/test-cases",
        response_model=TestCasePage,
        operation_id="list_test_cases",
        responses={k: v for k, v in _PROBLEMS.items() if k in {401, 403, 404, 422, 500}},
    )
    def list_test_cases(
        project_id: Annotated[str, Path(pattern=_UUID_PATTERN)],
        query: Annotated[ListQuery, Query()],
    ) -> TestCasePage | Response:
        parsed_id = _uuid(project_id)
        if parsed_id is None:
            return _invalid("path", "/project_id", "invalid_uuid")
        try:
            after = decode_test_case_cursor(parsed_id, query.cursor) if query.cursor else None
            page = service.list(parsed_id, limit=query.limit, after=after)
        except CursorInvalid:
            return _invalid("query", "/cursor", "cursor_invalid")
        except ProjectNotFound:
            return problem(404, "resource_not_found", "Request failed")
        return TestCasePage(
            items=[_summary(item) for item in page.items],
            next_cursor=(
                encode_test_case_cursor(parsed_id, page.next_after) if page.next_after else None
            ),
        )

    @router.get(
        "/api/v1/test-cases/{test_case_id}",
        response_model=TestCaseDetail,
        operation_id="get_test_case",
        responses={200: {"headers": {"ETag": _ETAG_HEADER}}, **_PROBLEMS},
    )
    def get_test_case(
        test_case_id: Annotated[str, Path(pattern=_UUID_PATTERN)],
        query: Annotated[EmptyQuery, Query()],
    ) -> Response:
        parsed_id = _uuid(test_case_id)
        if parsed_id is None:
            return _invalid("path", "/test_case_id", "invalid_uuid")
        try:
            test_case = service.get(parsed_id)
        except TestCaseNotFound:
            return problem(404, "resource_not_found", "Request failed")
        return _model_response(_detail(test_case), headers={"ETag": _etag(test_case)})

    @router.put(
        "/api/v1/test-cases/{test_case_id}",
        response_model=TestCaseDetail,
        operation_id="revise_test_case",
        responses={200: {"headers": {"ETag": _ETAG_HEADER}}, **_PROBLEMS},
    )
    def revise_test_case(
        test_case_id: Annotated[str, Path(pattern=_UUID_PATTERN)],
        command: TestCaseWrite,
        query: Annotated[EmptyQuery, Query()],
        if_match: Annotated[str | None, Header()] = None,
    ) -> Response:
        parsed_id = _uuid(test_case_id)
        if parsed_id is None:
            return _invalid("path", "/test_case_id", "invalid_uuid")
        expected = _parse_if_match(if_match, parsed_id)
        if not isinstance(expected, int):
            return expected
        try:
            test_case = service.update(
                parsed_id,
                expected_state_version=expected,
                name=command.name,
                definition=command.definition,
                unsafe_replay_acknowledgement=command.unsafe_replay_acknowledgement,
            )
        except TestCaseNotFound:
            return problem(404, "resource_not_found", "Request failed")
        except TestCaseRevisionConflict:
            return problem(412, "revision_conflict", "Revision conflict")
        except TestCaseVersionExhausted:
            return problem(409, "resource_conflict", "Resource conflict")
        except DefinitionValidationError as error:
            return _definition_error(error)
        except (TestCaseValidationError, ProjectValidationError) as error:
            if "acknowledgement" in str(error):
                return _invalid(
                    "body",
                    "/unsafe_replay_acknowledgement",
                    (
                        "incompatible_fields"
                        if "incompatible" in str(error)
                        else "unsafe_replay_acknowledgement_required"
                    ),
                )
            return _invalid("body", "/name", "value_invalid")
        return _model_response(_detail(test_case), headers={"ETag": _etag(test_case)})

    @router.get(
        "/api/v1/test-cases/{test_case_id}/revisions",
        response_model=TestCaseRevisionPage,
        operation_id="list_test_case_revisions",
        responses={k: v for k, v in _PROBLEMS.items() if k in {401, 403, 404, 422, 500}},
    )
    def list_test_case_revisions(
        test_case_id: Annotated[str, Path(pattern=_UUID_PATTERN)],
        query: Annotated[ListQuery, Query()],
    ) -> TestCaseRevisionPage | Response:
        parsed_id = _uuid(test_case_id)
        if parsed_id is None:
            return _invalid("path", "/test_case_id", "invalid_uuid")
        try:
            after = (
                decode_test_case_revision_cursor(parsed_id, query.cursor) if query.cursor else None
            )
            page = service.revisions(parsed_id, limit=query.limit, after=after)
        except CursorInvalid:
            return _invalid("query", "/cursor", "cursor_invalid")
        except TestCaseNotFound:
            return problem(404, "resource_not_found", "Request failed")
        return _model_response(_revision_page(parsed_id, page.items, page.next_after))

    return router

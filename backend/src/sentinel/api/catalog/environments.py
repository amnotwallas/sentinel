import re
from datetime import UTC, datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Header, Path, Query, Request, Response
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)

from sentinel.api.catalog.pagination import (
    CursorInvalid,
    decode_environment_cursor,
    encode_environment_cursor,
)
from sentinel.api.problems import Problem, field_problem, problem
from sentinel.catalog.environments import (
    Environment as DomainEnvironment,
)
from sentinel.catalog.environments import (
    EnvironmentNotFound,
    EnvironmentRevisionConflict,
    EnvironmentService,
    EnvironmentValidationError,
    EnvironmentVersionExhausted,
)
from sentinel.catalog.projects import (
    ProjectNotFound,
    ProjectValidationError,
    normalize_project_name,
)

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


class SecretReference(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, populate_by_name=True)
    secret: str = Field(alias="$secret", min_length=1, max_length=120)


class TargetPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: Literal[1] = 1
    allowed_hostnames: list[str] = Field(default_factory=list, max_length=128)
    allowed_cidrs: list[str] = Field(default_factory=list, max_length=128)
    denied_hostnames: list[str] = Field(default_factory=list, max_length=128)
    denied_cidrs: list[str] = Field(default_factory=list, max_length=128)
    allowed_ports: list[int] | None = Field(default=None, max_length=128)


class EnvironmentDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: Literal[1] = 1
    base_url: str = Field(min_length=1, max_length=2048)
    variables: dict[str, str] = Field(default_factory=dict)
    secret_references: list[SecretReference] = Field(default_factory=list, max_length=128)
    target_policy: TargetPolicy = Field(default_factory=TargetPolicy)


class EnvironmentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    name: str = Field(min_length=1, max_length=120)
    definition: EnvironmentDocument

    @field_validator("name", mode="before")
    @classmethod
    def valid_name(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        try:
            return normalize_project_name(value)
        except ProjectValidationError:
            raise ValueError("invalid environment name") from None


class EnvironmentPatch(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    name: str | None = Field(default=None, min_length=1, max_length=120)
    definition: EnvironmentDocument | None = None

    @field_validator("name", mode="before")
    @classmethod
    def valid_name(cls, value: object) -> object:
        if value is None:
            raise ValueError("environment name cannot be null")
        if not isinstance(value, str):
            return value
        try:
            return normalize_project_name(value)
        except ProjectValidationError:
            raise ValueError("invalid environment name") from None

    @field_validator("definition", mode="before")
    @classmethod
    def definition_is_not_null(cls, value: object) -> object:
        if value is None:
            raise ValueError("environment definition cannot be null")
        return value

    @model_validator(mode="after")
    def nonempty(self) -> "EnvironmentPatch":
        if self.name is None and self.definition is None:
            raise ValueError("environment patch must not be empty")
        return self


class EnvironmentRevision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID
    environment_id: UUID
    version: int = Field(ge=1)
    schema_version: Literal[1] = 1
    definition: EnvironmentDocument
    created_at: datetime

    @field_serializer("id", "environment_id")
    def serialize_uuid(self, value: UUID) -> str:
        return str(value)

    @field_serializer("created_at")
    def serialize_time(self, value: datetime) -> str:
        return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class EnvironmentDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID
    project_id: UUID
    name: str
    active_revision_id: UUID
    created_at: datetime
    updated_at: datetime
    active_revision: EnvironmentRevision

    @field_serializer("id", "project_id", "active_revision_id")
    def serialize_uuid(self, value: UUID) -> str:
        return str(value)

    @field_serializer("created_at", "updated_at")
    def serialize_time(self, value: datetime) -> str:
        return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class EnvironmentSummary(BaseModel):
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


class EnvironmentPage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[EnvironmentSummary] = Field(max_length=100)
    next_cursor: str | None = Field(min_length=1, max_length=2048)


class ListQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    limit: int = Field(default=50, ge=1, le=100)
    cursor: str | None = Field(default=None, min_length=1, max_length=2048)


class EmptyQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _document(environment: DomainEnvironment) -> EnvironmentDetail:
    revision = environment.active_revision
    return EnvironmentDetail(
        id=environment.id,
        project_id=environment.project_id,
        name=environment.name,
        active_revision_id=environment.active_revision_id,
        created_at=environment.created_at,
        updated_at=environment.updated_at,
        active_revision=EnvironmentRevision(
            id=revision.id,
            environment_id=revision.environment_id,
            version=revision.version,
            definition=EnvironmentDocument.model_validate(revision.definition.to_document()),
            created_at=revision.created_at,
        ),
    )


def _summary(environment: DomainEnvironment) -> EnvironmentSummary:
    return EnvironmentSummary(
        id=environment.id,
        project_id=environment.project_id,
        name=environment.name,
        active_revision_id=environment.active_revision_id,
        created_at=environment.created_at,
        updated_at=environment.updated_at,
        active_revision_version=environment.active_revision.version,
    )


def _etag(environment: DomainEnvironment) -> str:
    return f'"environment:{environment.id}:{environment.state_version}"'


def _uuid(value: str) -> UUID | None:
    try:
        parsed = UUID(value)
    except ValueError:
        return None
    return parsed if parsed.int != 0 and str(parsed) == value else None


def _parse_if_match(value: str | None, environment_id: UUID) -> int | Response:
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
    version = int(raw_version)
    if resource_id is None or version > 2_147_483_647:
        return field_problem(
            422,
            "validation_failed",
            "Request validation failed",
            location="header",
            pointer="/if-match",
            field_code="value_invalid",
        )
    if resource_kind != "environment" or resource_id != environment_id:
        return problem(412, "revision_conflict", "Revision conflict")
    return version


def environment_router(service: EnvironmentService) -> APIRouter:
    router = APIRouter(tags=["catalog"])

    @router.post(
        "/api/v1/projects/{project_id}/environments",
        response_model=EnvironmentDetail,
        status_code=201,
        operation_id="create_environment",
        responses={
            201: {"headers": {"ETag": _ETAG_HEADER, "Location": _LOCATION_HEADER}},
            **_PROBLEMS,
        },
    )
    def create_environment(
        project_id: Annotated[str, Path(pattern=_UUID_PATTERN)],
        command: EnvironmentCreate,
        response: Response,
        request: Request,
        query: Annotated[EmptyQuery, Query()],
    ) -> EnvironmentDetail | Response:
        if request.headers.get("if-match") is not None:
            return field_problem(
                422,
                "validation_failed",
                "Request validation failed",
                location="header",
                pointer="/if-match",
                field_code="incompatible_fields",
            )
        parsed_id = _uuid(project_id)
        if parsed_id is None:
            return field_problem(
                422,
                "validation_failed",
                "Request validation failed",
                location="path",
                pointer="/project_id",
                field_code="invalid_uuid",
            )
        try:
            environment = service.create(
                parsed_id,
                name=command.name,
                definition=command.definition.model_dump(by_alias=True),
            )
        except ProjectNotFound:
            return problem(404, "resource_not_found", "Request failed")
        except ProjectValidationError:
            return field_problem(
                422,
                "validation_failed",
                "Request validation failed",
                location="body",
                pointer="/name",
                field_code="value_invalid",
            )
        except EnvironmentValidationError:
            return field_problem(
                422,
                "validation_failed",
                "Request validation failed",
                location="body",
                pointer="/definition",
                field_code="value_invalid",
            )
        response.headers["Location"] = f"/api/v1/environments/{environment.id}"
        response.headers["ETag"] = _etag(environment)
        return _document(environment)

    @router.get(
        "/api/v1/projects/{project_id}/environments",
        response_model=EnvironmentPage,
        operation_id="list_environments",
        responses={k: v for k, v in _PROBLEMS.items() if k in {401, 403, 404, 422, 500}},
    )
    def list_environments(
        project_id: Annotated[str, Path(pattern=_UUID_PATTERN)],
        query: Annotated[ListQuery, Query()],
    ) -> EnvironmentPage | Response:
        parsed_id = _uuid(project_id)
        if parsed_id is None:
            return field_problem(
                422,
                "validation_failed",
                "Request validation failed",
                location="path",
                pointer="/project_id",
                field_code="invalid_uuid",
            )
        try:
            after = (
                decode_environment_cursor(parsed_id, query.cursor)
                if query.cursor is not None
                else None
            )
            page = service.list(parsed_id, limit=query.limit, after=after)
        except CursorInvalid:
            return field_problem(
                422,
                "validation_failed",
                "Request validation failed",
                location="query",
                pointer="/cursor",
                field_code="cursor_invalid",
            )
        except ProjectNotFound:
            return problem(404, "resource_not_found", "Request failed")
        return EnvironmentPage(
            items=[_summary(item) for item in page.items],
            next_cursor=(
                encode_environment_cursor(parsed_id, page.next_after)
                if page.next_after is not None
                else None
            ),
        )

    @router.get(
        "/api/v1/environments/{environment_id}",
        response_model=EnvironmentDetail,
        operation_id="get_environment",
        responses={
            200: {"headers": {"ETag": _ETAG_HEADER}},
            **{k: v for k, v in _PROBLEMS.items() if k in {401, 403, 404, 422, 500}},
        },
    )
    def get_environment(
        environment_id: Annotated[str, Path(pattern=_UUID_PATTERN)],
        response: Response,
        query: Annotated[EmptyQuery, Query()],
    ) -> EnvironmentDetail | Response:
        parsed_id = _uuid(environment_id)
        if parsed_id is None:
            return field_problem(
                422,
                "validation_failed",
                "Request validation failed",
                location="path",
                pointer="/environment_id",
                field_code="invalid_uuid",
            )
        try:
            environment = service.get(parsed_id)
        except EnvironmentNotFound:
            return problem(404, "resource_not_found", "Request failed")
        response.headers["ETag"] = _etag(environment)
        return _document(environment)

    @router.patch(
        "/api/v1/environments/{environment_id}",
        response_model=EnvironmentDetail,
        operation_id="update_environment",
        responses={200: {"headers": {"ETag": _ETAG_HEADER}}, **_PROBLEMS},
    )
    def update_environment(
        environment_id: Annotated[str, Path(pattern=_UUID_PATTERN)],
        command: EnvironmentPatch,
        response: Response,
        query: Annotated[EmptyQuery, Query()],
        if_match: Annotated[str | None, Header()] = None,
    ) -> EnvironmentDetail | Response:
        parsed_id = _uuid(environment_id)
        if parsed_id is None:
            return field_problem(
                422,
                "validation_failed",
                "Request validation failed",
                location="path",
                pointer="/environment_id",
                field_code="invalid_uuid",
            )
        expected = _parse_if_match(if_match, parsed_id)
        if not isinstance(expected, int):
            return expected
        try:
            environment = service.update(
                parsed_id,
                expected_state_version=expected,
                name=command.name,
                definition=(
                    command.definition.model_dump(by_alias=True)
                    if command.definition is not None
                    else None
                ),
            )
        except EnvironmentNotFound:
            return problem(404, "resource_not_found", "Request failed")
        except EnvironmentRevisionConflict:
            return problem(412, "revision_conflict", "Revision conflict")
        except EnvironmentVersionExhausted:
            return problem(409, "resource_conflict", "Resource conflict")
        except ProjectValidationError:
            return field_problem(
                422,
                "validation_failed",
                "Request validation failed",
                location="body",
                pointer="/name",
                field_code="value_invalid",
            )
        except EnvironmentValidationError:
            return field_problem(
                422,
                "validation_failed",
                "Request validation failed",
                location="body",
                pointer="/definition",
                field_code="value_invalid",
            )
        response.headers["ETag"] = _etag(environment)
        return _document(environment)

    return router

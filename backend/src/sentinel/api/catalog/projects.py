from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Path, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

from sentinel.api.catalog.pagination import (
    CursorInvalid,
    decode_project_cursor,
    encode_project_cursor,
)
from sentinel.api.problems import Problem, field_problem, problem
from sentinel.catalog.projects import Project as DomainProject
from sentinel.catalog.projects import (
    ProjectNameConflict,
    ProjectNotFound,
    ProjectService,
    ProjectValidationError,
    normalize_project_name,
)

_UUID_PATTERN = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
# FastAPI's public `responses` metadata contract is typed with `Any`.
_PROBLEMS: dict[int | str, dict[str, Any]] = {
    status: {
        "model": Problem,
        "description": "RFC 9457 problem response",
        "content": {"application/problem+json": {}},
    }
    for status in (401, 403, 404, 409, 413, 415, 422, 500)
}
_ETAG_HEADER: dict[str, Any] = {
    "schema": {"type": "string"},
    "description": "Strong resource ETag",
}
_LOCATION_HEADER: dict[str, Any] = {
    "schema": {"type": "string"},
    "description": "Created resource path",
}


class ProjectCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    name: str = Field(min_length=1, max_length=120)

    @field_validator("name", mode="before")
    @classmethod
    def valid_name(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        try:
            return normalize_project_name(value)
        except ProjectValidationError:
            raise ValueError("invalid project name") from None


class Project(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID = Field(json_schema_extra={"format": "uuid", "pattern": _UUID_PATTERN})
    name: str = Field(min_length=1, max_length=120)
    created_at: datetime = Field(json_schema_extra={"format": "date-time"})
    deleted_at: None

    @field_serializer("id")
    def serialize_id(self, value: UUID) -> str:
        return str(value)

    @field_serializer("created_at")
    def serialize_created_at(self, value: datetime) -> str:
        return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class ProjectPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[Project] = Field(max_length=100)
    next_cursor: str | None = Field(min_length=1, max_length=2048)


class ProjectListQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    limit: int = Field(default=50, ge=1, le=100)
    cursor: str | None = Field(default=None, min_length=1, max_length=2048)


class EmptyQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _output(project: DomainProject) -> Project:
    return Project(
        id=project.id,
        name=project.name,
        created_at=project.created_at,
        deleted_at=None,
    )


def _etag(project: DomainProject) -> str:
    return f'"project:{project.id}:{project.state_version}"'


def project_router(service: ProjectService) -> APIRouter:
    router = APIRouter(prefix="/api/v1/projects", tags=["catalog"])

    @router.post(
        "",
        response_model=Project,
        status_code=201,
        operation_id="create_project",
        responses={
            201: {"headers": {"ETag": _ETAG_HEADER, "Location": _LOCATION_HEADER}},
            **_PROBLEMS,
        },
    )
    def create_project(
        command: ProjectCreate,
        response: Response,
        request: Request,
        query: Annotated[EmptyQuery, Query()],
    ) -> Project | Response:
        if request.headers.get("if-match") is not None:
            return field_problem(
                422,
                "validation_failed",
                "Request validation failed",
                location="header",
                pointer="/if-match",
                field_code="incompatible_fields",
            )
        try:
            project = service.create(command.name)
        except ProjectNameConflict:
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
        response.headers["Location"] = f"/api/v1/projects/{project.id}"
        response.headers["ETag"] = _etag(project)
        return _output(project)

    @router.get(
        "",
        response_model=ProjectPage,
        operation_id="list_projects",
        responses={
            status: definition
            for status, definition in _PROBLEMS.items()
            if status not in {409, 413, 415}
        },
    )
    def list_projects(
        query: Annotated[ProjectListQuery, Query()],
    ) -> ProjectPage | Response:
        try:
            after = decode_project_cursor(query.cursor) if query.cursor is not None else None
        except CursorInvalid:
            return field_problem(
                422,
                "validation_failed",
                "Request validation failed",
                location="query",
                pointer="/cursor",
                field_code="cursor_invalid",
            )
        page = service.list(limit=query.limit, after=after)
        return ProjectPage(
            items=[_output(project) for project in page.items],
            next_cursor=(
                encode_project_cursor(page.next_after) if page.next_after is not None else None
            ),
        )

    @router.get(
        "/{project_id}",
        response_model=Project,
        operation_id="get_project",
        responses={
            200: {"headers": {"ETag": _ETAG_HEADER}},
            **{
                status: definition
                for status, definition in _PROBLEMS.items()
                if status not in {409, 413, 415}
            },
        },
    )
    def get_project(
        project_id: Annotated[str, Path(pattern=_UUID_PATTERN)],
        response: Response,
        query: Annotated[EmptyQuery, Query()],
    ) -> Project | Response:
        parsed_id = UUID(project_id)
        if parsed_id.int == 0:
            return field_problem(
                422,
                "validation_failed",
                "Request validation failed",
                location="path",
                pointer="/project_id",
                field_code="invalid_uuid",
            )
        try:
            project = service.get(parsed_id)
        except ProjectNotFound:
            return problem(404, "resource_not_found", "Request failed")
        response.headers["ETag"] = _etag(project)
        return _output(project)

    return router

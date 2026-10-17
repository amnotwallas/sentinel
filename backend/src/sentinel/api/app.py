import asyncio
import secrets
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

import httpx
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel
from starlette.exceptions import HTTPException
from starlette.responses import Response

from sentinel.api.body_limit import BodyLimitMiddleware
from sentinel.api.catalog.catalog_openapi import catalog_schemas
from sentinel.api.catalog.environments import environment_router
from sentinel.api.catalog.projects import project_router
from sentinel.api.catalog.suite_openapi import suite_schemas
from sentinel.api.catalog.suites import suite_router
from sentinel.api.catalog.test_case_openapi import test_case_schemas
from sentinel.api.catalog.test_cases import test_case_router
from sentinel.api.executions import execution_router
from sentinel.api.problems import problem, validation_problem
from sentinel.catalog.environments import EnvironmentService
from sentinel.catalog.projects import ProjectService
from sentinel.catalog.suites import SuiteService
from sentinel.catalog.test_cases import TestCaseService
from sentinel.config import Settings
from sentinel.execution.creation import PostgresExecutionService
from sentinel.persistence.catalog.unit_of_work import PostgresCatalogUnitOfWork
from sentinel.persistence.database import create_database
from sentinel.persistence.readiness import database_is_current
from sentinel.security.definition_policy import (
    validate_environment_document,
    validate_test_definition,
)
from sentinel.telemetry.runtime import provider

Probe = Callable[[], Awaitable[bool]]


class SentinelAPI(FastAPI):
    def openapi(self) -> dict[str, Any]:
        schema = super().openapi()
        schema.setdefault("components", {}).setdefault("schemas", {}).update(catalog_schemas())
        schema["components"]["schemas"].update(test_case_schemas())
        schema["components"]["schemas"].update(suite_schemas())
        _normalize_execution_openapi(schema)
        # FastAPI always adds its default JSON media type for a documented model.
        # Sentinel problem responses use RFC 9457's dedicated media type instead.
        for path in schema.get("paths", {}).values():
            for operation in path.values():
                for response in operation.get("responses", {}).values():
                    content = response.get("content", {})
                    if "application/problem+json" in content:
                        json_content = content.pop("application/json", None)
                        if json_content and not content["application/problem+json"]:
                            content["application/problem+json"] = json_content
        for path, method in (
            ("/api/v1/environments/{environment_id}", "patch"),
            ("/api/v1/test-cases/{test_case_id}", "put"),
            ("/api/v1/suites/{suite_id}", "put"),
        ):
            update = schema.get("paths", {}).get(path, {}).get(method)
            if update is not None:
                for parameter in update.get("parameters", []):
                    if parameter.get("in") == "header" and parameter.get("name") == "if-match":
                        # Runtime handles absence itself to return the contractual 428.
                        parameter["required"] = True
        return schema


def _normalize_execution_openapi(schema: dict[str, Any]) -> None:
    """Apply the shared UUID/timestamp primitives to execution schemas.

    The execution models need Python ``UUID``/``datetime`` values for service
    boundaries, while the public contract uses the repository's stricter
    canonical primitives. Keep this normalization in the runtime OpenAPI
    composition layer alongside the existing catalog schema composition.
    """

    schemas = schema.get("components", {}).get("schemas", {})
    uuid_ref = {"$ref": "#/components/schemas/UUID"}
    timestamp_ref = {"$ref": "#/components/schemas/Timestamp"}
    nullable_timestamp = {"anyOf": [timestamp_ref, {"type": "null"}]}
    id_fields = {
        "ChangeEventOutput": {"id", "project_id", "subject_id", "before_ref", "after_ref"},
        "AttemptSummary": {"id", "replayed_by_attempt_id"},
        "ExecutionItem": {"id", "test_case_id", "test_case_revision_id"},
        "ExecutionSummary": {
            "id",
            "project_id",
            "environment_id",
            "environment_revision_id",
            "source_id",
            "source_revision_id",
        },
        "ExecutionDetail": {
            "id",
            "project_id",
            "environment_id",
            "environment_revision_id",
            "source_id",
            "source_revision_id",
        },
    }
    for name, fields in id_fields.items():
        properties = schemas.get(name, {}).get("properties", {})
        for field in fields:
            if field in properties:
                properties[field] = (
                    uuid_ref
                    if field not in {"before_ref", "after_ref", "replayed_by_attempt_id"}
                    else {"anyOf": [uuid_ref, {"type": "null"}]}
                )

    required_timestamps = {
        "ChangeEventOutput": {"created_at"},
        "AttemptSummary": {"created_at"},
        "ExecutionSummary": {"created_at"},
        "ExecutionDetail": {"created_at"},
    }
    optional_timestamps = {
        "AttemptSummary": {"dispatch_recorded_at", "response_recorded_at", "finished_at"},
        "ExecutionItem": {"started_at", "finished_at"},
        "ExecutionSummary": {"started_at", "finished_at"},
        "ExecutionDetail": {"started_at", "finished_at"},
    }
    for name, fields in required_timestamps.items():
        properties = schemas.get(name, {}).get("properties", {})
        for field in fields:
            if field in properties:
                properties[field] = timestamp_ref
    for name, fields in optional_timestamps.items():
        properties = schemas.get(name, {}).get("properties", {})
        for field in fields:
            if field in properties:
                properties[field] = nullable_timestamp

    create = schemas.get("ExecutionCreate", {})
    schemas["ExecutionCreateTestCase"] = {
        "additionalProperties": False,
        "properties": {
            "environment_id": uuid_ref,
            "test_case_id": uuid_ref,
        },
        "required": ["environment_id", "test_case_id"],
        "type": "object",
    }
    schemas["ExecutionCreateSuite"] = {
        "additionalProperties": False,
        "properties": {
            "environment_id": uuid_ref,
            "suite_id": uuid_ref,
        },
        "required": ["environment_id", "suite_id"],
        "type": "object",
    }
    create.clear()
    create.update(
        {
            "oneOf": [
                {"$ref": "#/components/schemas/ExecutionCreateTestCase"},
                {"$ref": "#/components/schemas/ExecutionCreateSuite"},
            ],
            "title": "ExecutionCreate",
        }
    )

    query = schema.get("paths", {}).get("/api/v1/executions", {}).get("get", {})
    for parameter in query.get("parameters", []):
        if parameter.get("name") in {"project_id", "environment_id", "test_case_id", "suite_id"}:
            parameter["schema"] = uuid_ref
        elif parameter.get("name") in {"created_from", "created_before"}:
            parameter["schema"] = timestamp_ref


class Liveness(BaseModel):
    status: Literal["alive"] = "alive"


class Readiness(BaseModel):
    status: Literal["ready", "unavailable"]
    postgres: Literal["available", "unavailable"]
    tempo: Literal["available", "unavailable"]


def create_app(
    settings: Settings | None = None,
    *,
    database_probe: Probe | None = None,
    tempo_probe: Probe | None = None,
    project_service: ProjectService | None = None,
    environment_service: EnvironmentService | None = None,
    test_case_service: TestCaseService | None = None,
    suite_service: SuiteService | None = None,
    execution_service: PostgresExecutionService | None = None,
) -> FastAPI:
    settings = settings or Settings()
    engine, sessions = create_database(settings.database_url.get_secret_value())
    tracing = provider("sentinel-api", settings.otlp_endpoint)
    tracer = tracing.get_tracer(__name__)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        await asyncio.to_thread(engine.dispose)
        await asyncio.to_thread(tracing.shutdown)

    app = SentinelAPI(title="Sentinel", version="0.1.0", lifespan=lifespan)
    catalog = project_service or ProjectService(
        lambda: PostgresCatalogUnitOfWork(sessions),
        ids=uuid4,
        clock=lambda: datetime.now(UTC),
    )
    app.include_router(project_router(catalog))
    environments = environment_service or EnvironmentService(
        lambda: PostgresCatalogUnitOfWork(sessions),
        ids=uuid4,
        clock=lambda: datetime.now(UTC),
        validate_document=validate_environment_document,
    )
    app.include_router(environment_router(environments))
    test_cases = test_case_service or TestCaseService(
        lambda: PostgresCatalogUnitOfWork(sessions),
        ids=uuid4,
        clock=lambda: datetime.now(UTC),
        validate_document=validate_test_definition,
    )
    app.include_router(test_case_router(test_cases))
    suites = suite_service or SuiteService(
        lambda: PostgresCatalogUnitOfWork(sessions),
        ids=uuid4,
        clock=lambda: datetime.now(UTC),
    )
    app.include_router(suite_router(suites))
    executions = execution_service or PostgresExecutionService(
        sessions,
        ids=uuid4,
        clock=lambda: datetime.now(UTC),
        max_deliveries=settings.max_deliveries,
    )
    app.include_router(execution_router(executions))

    async def tempo_ready() -> bool:
        try:
            async with httpx.AsyncClient(timeout=1, trust_env=False) as client:
                response = await client.get(f"{settings.tempo_url.rstrip('/')}/ready")
                return response.status_code == 200
        except httpx.HTTPError:
            return False

    app.add_middleware(BodyLimitMiddleware, max_bytes=524_288)

    @app.middleware("http")
    async def boundary(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        token = settings.api_token
        if token and request.url.path not in {"/health/live", "/health/ready"}:
            supplied = request.headers.get("authorization", "")
            expected = f"Bearer {token.get_secret_value()}"
            if not secrets.compare_digest(supplied.encode("utf-8"), expected.encode("utf-8")):
                return problem(401, "authentication_required", "Authentication required")
        with tracer.start_as_current_span(
            "api.request",
            record_exception=False,
            set_status_on_exception=False,
            attributes={"http.request.method": request.method},
        ) as span:
            try:
                response = await call_next(request)
            except Exception:
                response = problem(500, "internal_error", "Internal server error")
            span.set_attribute("http.response.status_code", response.status_code)
            return response

    @app.exception_handler(HTTPException)
    async def http_error(_: Request, error: HTTPException) -> Response:
        return problem(
            error.status_code,
            "resource_not_found" if error.status_code == 404 else "http_error",
            "Request failed",
        )

    @app.exception_handler(RequestValidationError)
    async def invalid(_: Request, error: RequestValidationError) -> Response:
        return validation_problem(error)

    @app.get("/health/live", response_model=Liveness)
    async def live() -> Liveness:
        return Liveness()

    @app.get("/health/ready", response_model=Readiness, responses={503: {"model": Readiness}})
    async def ready(response: Response) -> Readiness:
        postgres, tempo = await asyncio.gather(
            database_probe() if database_probe else asyncio.to_thread(database_is_current, engine),
            tempo_probe() if tempo_probe else tempo_ready(),
        )
        response.status_code = 200 if postgres else 503
        return Readiness(
            status="ready" if postgres else "unavailable",
            postgres="available" if postgres else "unavailable",
            tempo="available" if tempo else "unavailable",
        )

    return app

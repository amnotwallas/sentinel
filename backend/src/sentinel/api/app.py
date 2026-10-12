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
from sentinel.api.catalog.environments import environment_router
from sentinel.api.catalog.projects import project_router
from sentinel.api.problems import problem, validation_problem
from sentinel.catalog.environments import EnvironmentService
from sentinel.catalog.projects import ProjectService
from sentinel.config import Settings
from sentinel.persistence.catalog.unit_of_work import PostgresCatalogUnitOfWork
from sentinel.persistence.database import create_database
from sentinel.persistence.readiness import database_is_current
from sentinel.security.definition_policy import validate_environment_document
from sentinel.telemetry.runtime import provider

Probe = Callable[[], Awaitable[bool]]


class SentinelAPI(FastAPI):
    def openapi(self) -> dict[str, Any]:
        schema = super().openapi()
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
        update = (
            schema.get("paths", {}).get("/api/v1/environments/{environment_id}", {}).get("patch")
        )
        if update is not None:
            for parameter in update.get("parameters", []):
                if parameter.get("in") == "header" and parameter.get("name") == "if-match":
                    # Runtime handles absence itself to return the contractual 428.
                    parameter["required"] = True
        return schema


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

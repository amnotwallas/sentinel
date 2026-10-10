import asyncio
import secrets
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Literal

import httpx
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel
from sqlalchemy import text
from starlette.exceptions import HTTPException
from starlette.responses import Response

from sentinel.api.problems import problem, validation_problem
from sentinel.config import Settings
from sentinel.persistence.database import create_database
from sentinel.telemetry.runtime import provider

Probe = Callable[[], Awaitable[bool]]


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
) -> FastAPI:
    settings = settings or Settings()
    engine, _ = create_database(settings.database_url.get_secret_value())
    tracing = provider("sentinel-api", settings.otlp_endpoint)
    tracer = tracing.get_tracer(__name__)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        await asyncio.to_thread(engine.dispose)
        await asyncio.to_thread(tracing.shutdown)

    app = FastAPI(title="Sentinel", version="0.1.0", lifespan=lifespan)

    def postgres_ready() -> bool:
        try:
            with engine.connect() as conn:
                version = conn.scalar(text("SELECT version_num FROM alembic_version"))
                return isinstance(version, str) and version == "0001"
        except Exception:
            return False

    async def tempo_ready() -> bool:
        try:
            async with httpx.AsyncClient(timeout=1, trust_env=False) as client:
                response = await client.get(f"{settings.tempo_url.rstrip('/')}/ready")
                return response.status_code == 200
        except httpx.HTTPError:
            return False

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
            database_probe() if database_probe else asyncio.to_thread(postgres_ready),
            tempo_probe() if tempo_probe else tempo_ready(),
        )
        response.status_code = 200 if postgres else 503
        return Readiness(
            status="ready" if postgres else "unavailable",
            postgres="available" if postgres else "unavailable",
            tempo="available" if tempo else "unavailable",
        )

    return app

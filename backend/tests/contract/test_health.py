from collections.abc import AsyncIterator

import httpx
import pytest
from fastapi.exceptions import RequestValidationError
from pydantic import SecretStr

from sentinel.api.app import create_app
from sentinel.api.problems import validation_problem
from sentinel.config import Settings


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    async def database() -> bool:
        return True

    async def tempo() -> bool:
        return False

    app = create_app(Settings(), database_probe=database, tempo_probe=tempo)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://testserver"
        ) as client,
    ):
        yield client


async def test_tempo_degradation_does_not_fail_readiness(client: httpx.AsyncClient) -> None:
    response = await client.get("/health/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready", "postgres": "available", "tempo": "unavailable"}


async def test_liveness_does_not_need_database(client: httpx.AsyncClient) -> None:
    response = await client.get("/health/live")
    assert response.json() == {"status": "alive"}


async def test_unknown_route_returns_problem_without_echoing_path(
    client: httpx.AsyncClient,
) -> None:
    response = await client.get("/canary-secret")
    assert response.status_code == 404
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["code"] == "resource_not_found"
    assert "canary-secret" not in response.text


async def test_database_unavailable_returns_503() -> None:
    async def unavailable() -> bool:
        return False

    app = create_app(Settings(), database_probe=unavailable, tempo_probe=unavailable)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://testserver"
        ) as client,
    ):
        response = await client.get("/health/ready")
    assert response.status_code == 503
    assert response.json()["postgres"] == "unavailable"


async def test_remote_bind_protects_api_docs_but_allows_liveness() -> None:
    app = create_app(Settings(api_host="0.0.0.0", api_token=SecretStr("canary-token")))
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://testserver"
        ) as client,
    ):
        assert (await client.get("/health/live")).status_code == 200
        assert (await client.get("/openapi.json")).status_code == 401
        response = await client.get(
            "/openapi.json", headers={"Authorization": "Bearer canary-token"}
        )
        assert response.status_code == 200
        assert "canary-token" not in response.text


def test_validation_problem_does_not_echo_input() -> None:
    # All exposed M1 routes have no user inputs; characterization of shared error renderer.
    error = RequestValidationError([{"type": "bad", "loc": ["body"], "input": "canary-secret"}])
    response = validation_problem(error)
    assert response.status_code == 422
    assert b"canary-secret" not in response.body


async def test_non_ascii_authentication_header_is_rejected_cleanly() -> None:
    app = create_app(Settings(api_host="0.0.0.0", api_token=SecretStr("canary-token")))
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://testserver"
        ) as client,
    ):
        response = await client.get("/openapi.json", headers={b"Authorization": b"Bearer \xff"})
    assert response.status_code == 401
    assert response.json()["code"] == "authentication_required"

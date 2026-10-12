import socket

import httpx
import pytest
from pydantic import SecretStr

from sentinel.api.app import create_app
from sentinel.config import Settings


async def test_connection_failure_is_not_ready_without_exposing_connection_details(
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def tempo() -> bool:
        return False

    # A reserved loopback port without a listener rejects the real psycopg connection.
    with socket.socket() as unused_port:
        unused_port.bind(("127.0.0.1", 0))
        port = unused_port.getsockname()[1]
        app = create_app(
            Settings(
                database_url=SecretStr(
                    f"postgresql+psycopg://sentinel:canary-password@127.0.0.1:{port}/unavailable"
                ),
                otlp_endpoint=None,
            ),
            tempo_probe=tempo,
        )
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app), base_url="http://testserver"
            ) as client,
        ):
            response = await client.get("/health/ready")
            assert response.status_code == 503
            assert response.json()["postgres"] == "unavailable"
            assert "canary-password" not in response.text
            assert "postgresql" not in response.text
            assert (await client.get("/health/live")).status_code == 200
    assert "canary-password" not in caplog.text

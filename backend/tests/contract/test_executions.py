from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

import httpx
import pytest

from sentinel.api.app import create_app
from sentinel.config import Settings
from sentinel.execution.creation import (
    ExecutionCreateCommand,
    ExecutionIdempotencyConflict,
    ExecutionItemRecord,
    ExecutionPageRecord,
    ExecutionRecord,
    PostgresExecutionService,
)

NOW = datetime(2030, 1, 1, 12, 30, tzinfo=UTC)
PROJECT_ID = UUID("00000000-0000-4000-8000-000000000001")
ENVIRONMENT_ID = UUID("00000000-0000-4000-8000-000000000002")
ENVIRONMENT_REVISION_ID = UUID("00000000-0000-4000-8000-000000000003")
TEST_CASE_ID = UUID("00000000-0000-4000-8000-000000000004")
TEST_CASE_REVISION_ID = UUID("00000000-0000-4000-8000-000000000005")
EXECUTION_ID = UUID("00000000-0000-4000-8000-000000000006")
ITEM_ID = UUID("00000000-0000-4000-8000-000000000007")


def _record() -> ExecutionRecord:
    return ExecutionRecord(
        id=EXECUTION_ID,
        project_id=PROJECT_ID,
        environment_id=ENVIRONMENT_ID,
        environment_revision_id=ENVIRONMENT_REVISION_ID,
        source_type="test_case",
        source_id=TEST_CASE_ID,
        source_revision_id=TEST_CASE_REVISION_ID,
        status="queued",
        verdict=None,
        created_at=NOW,
        started_at=None,
        finished_at=None,
        items=(
            ExecutionItemRecord(
                id=ITEM_ID,
                ordinal=0,
                test_case_id=TEST_CASE_ID,
                test_case_revision_id=TEST_CASE_REVISION_ID,
                test_case_revision_version=1,
                status="pending",
                verdict=None,
                started_at=None,
                finished_at=None,
            ),
        ),
    )


class MemoryExecutionService:
    def __init__(self) -> None:
        self.record = _record()
        self.conflict = False

    def create(
        self, command: ExecutionCreateCommand, *, idempotency_key: str | None = None
    ) -> ExecutionRecord:
        assert command.environment_id == ENVIRONMENT_ID
        assert command.test_case_id == TEST_CASE_ID
        if self.conflict:
            raise ExecutionIdempotencyConflict
        return self.record

    def get(self, execution_id: UUID) -> ExecutionRecord | None:
        return self.record if execution_id == self.record.id else None

    def list(self, **_: object) -> ExecutionPageRecord:
        return ExecutionPageRecord(items=(self.record,), next_after=None)


@pytest.fixture
async def client() -> AsyncIterator[tuple[httpx.AsyncClient, MemoryExecutionService]]:
    service = MemoryExecutionService()
    app = create_app(
        Settings(otlp_endpoint=None),
        database_probe=lambda: _ready(),
        tempo_probe=lambda: _not_ready(),
        execution_service=cast(PostgresExecutionService, service),
    )
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://testserver"
        ) as client,
    ):
        yield client, service


async def _ready() -> bool:
    return True


async def _not_ready() -> bool:
    return False


async def test_create_returns_bounded_queued_detail_and_location(
    client: tuple[httpx.AsyncClient, MemoryExecutionService],
) -> None:
    http_client, _ = client
    response = await http_client.post(
        "/api/v1/executions",
        json={"environment_id": str(ENVIRONMENT_ID), "test_case_id": str(TEST_CASE_ID)},
        headers={"Idempotency-Key": "synthetic-key"},
    )
    assert response.status_code == 202
    assert response.headers["location"] == f"/api/v1/executions/{EXECUTION_ID}"
    body = response.json()
    assert body["status"] == "queued"
    assert body["items"][0]["attempts"] == []
    assert body["change_evidence"] == []
    assert "synthetic-key" not in response.text


async def test_same_key_conflict_is_safe_problem(
    client: tuple[httpx.AsyncClient, MemoryExecutionService],
) -> None:
    http_client, service = client
    service.conflict = True
    response = await http_client.post(
        "/api/v1/executions",
        json={"environment_id": str(ENVIRONMENT_ID), "test_case_id": str(TEST_CASE_ID)},
        headers={"Idempotency-Key": "synthetic-key"},
    )
    assert response.status_code == 409
    assert response.json() == {
        "type": "urn:sentinel:problem:idempotency_conflict",
        "title": "Idempotency conflict",
        "status": 409,
        "code": "idempotency_conflict",
    }


async def test_openapi_publishes_execution_routes_and_closed_enums(
    client: tuple[httpx.AsyncClient, MemoryExecutionService],
) -> None:
    http_client, _ = client
    document = (await http_client.get("/openapi.json")).json()
    assert set(document["paths"]["/api/v1/executions"]) == {"get", "post"}
    assert "/api/v1/executions/{execution_id}" in document["paths"]
    assert document["components"]["schemas"]["ExecutionStatus"]["enum"] == [
        "queued",
        "running",
        "completed",
        "failed",
    ]
    schemas = document["components"]["schemas"]
    assert schemas["ExecutionSummary"]["properties"]["id"] == {"$ref": "#/components/schemas/UUID"}
    assert schemas["ExecutionSummary"]["properties"]["created_at"] == {
        "$ref": "#/components/schemas/Timestamp"
    }
    assert schemas["AttemptSummary"]["properties"]["dispatch_recorded_at"] == {
        "anyOf": [
            {"$ref": "#/components/schemas/Timestamp"},
            {"type": "null"},
        ]
    }
    create = schemas["ExecutionCreate"]
    assert create["oneOf"] == [
        {"$ref": "#/components/schemas/ExecutionCreateTestCase"},
        {"$ref": "#/components/schemas/ExecutionCreateSuite"},
    ]
    assert schemas["ExecutionCreateTestCase"]["properties"]["test_case_id"] == {
        "$ref": "#/components/schemas/UUID"
    }
    assert schemas["ExecutionCreateSuite"]["properties"]["suite_id"] == {
        "$ref": "#/components/schemas/UUID"
    }


async def test_list_accepts_uuid_filters_and_rejects_conflicting_sources(
    client: tuple[httpx.AsyncClient, MemoryExecutionService],
) -> None:
    http_client, _ = client
    listed = await http_client.get(
        "/api/v1/executions", params={"environment_id": str(ENVIRONMENT_ID)}
    )
    assert listed.status_code == 200
    assert listed.json()["items"][0]["id"] == str(EXECUTION_ID)
    conflict = await http_client.get(
        "/api/v1/executions",
        params={
            "test_case_id": str(TEST_CASE_ID),
            "suite_id": str(UUID("00000000-0000-4000-8000-000000000008")),
        },
    )
    assert conflict.status_code == 422


async def test_malformed_cursor_is_a_safe_validation_problem(
    client: tuple[httpx.AsyncClient, MemoryExecutionService],
) -> None:
    http_client, _ = client
    response = await http_client.get("/api/v1/executions", params={"cursor": "W10"})
    assert response.status_code == 422
    assert response.json()["code"] == "validation_failed"


async def test_execution_create_rejects_explicit_null_source(
    client: tuple[httpx.AsyncClient, MemoryExecutionService],
) -> None:
    http_client, _ = client
    response = await http_client.post(
        "/api/v1/executions",
        json={"environment_id": str(ENVIRONMENT_ID), "test_case_id": None},
    )
    assert response.status_code == 422

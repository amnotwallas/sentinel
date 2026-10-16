from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import UUID

import httpx
import pytest

from sentinel.api.app import create_app
from sentinel.catalog.projects import Project, ProjectService
from sentinel.catalog.test_cases import TestCase as DomainTestCase
from sentinel.catalog.test_cases import TestCaseRevision as DomainTestCaseRevision
from sentinel.catalog.test_cases import TestCaseService as Service
from sentinel.config import Settings
from sentinel.security.definition_policy import validate_test_definition

PROJECT_ID = UUID("00000000-0000-4000-8000-000000000001")
TEST_CASE_ID = UUID("00000000-0000-4000-8000-000000000010")
REVISION_1_ID = UUID("00000000-0000-4000-8000-000000000011")
EVENT_1_ID = UUID("00000000-0000-4000-8000-000000000012")
REVISION_2_ID = UUID("00000000-0000-4000-8000-000000000013")
EVENT_2_ID = UUID("00000000-0000-4000-8000-000000000014")
NOW = datetime(2030, 1, 1, 12, 30, tzinfo=UTC)


def definition(path: str = "/health") -> dict[str, object]:
    return {
        "request": {
            "method": "GET",
            "path": path,
            "headers": [{"name": "X-Synthetic", "value": "fixture"}],
        },
        "assertions": [],
        "comparison_policy": {},
        "redaction": {},
        "allow_unsafe_replay": False,
    }


class MemoryProjects:
    def __init__(self) -> None:
        self.items = {PROJECT_ID: Project(PROJECT_ID, "Synthetic", NOW, None, 1)}

    def add(self, project: Project) -> None:
        self.items[project.id] = project

    def get(self, project_id: UUID) -> Project | None:
        return self.items.get(project_id)

    def list_after(self, *, after: tuple[datetime, UUID] | None, limit: int) -> list[Project]:
        return list(self.items.values())[:limit]


class MemoryTestCaseRepo:
    def __init__(self) -> None:
        self.items: dict[UUID, DomainTestCase] = {}
        self.revisions: dict[UUID, list[DomainTestCaseRevision]] = {}

    def add(self, test_case: DomainTestCase) -> None:
        self.items[test_case.id] = test_case
        self.revisions[test_case.id] = [test_case.active_revision]

    def get(self, test_case_id: UUID, *, for_update: bool = False) -> DomainTestCase | None:
        return self.items.get(test_case_id)

    def replace(self, test_case: DomainTestCase) -> None:
        self.items[test_case.id] = test_case
        self.revisions[test_case.id].append(test_case.active_revision)

    def list_after(
        self,
        *,
        project_id: UUID,
        after: tuple[datetime, UUID] | None,
        limit: int,
    ) -> list[DomainTestCase]:
        items = [item for item in self.items.values() if item.project_id == project_id]
        return sorted(items, key=lambda item: (item.created_at, item.id))[:limit]

    def list_revisions_after(
        self,
        *,
        test_case_id: UUID,
        after: tuple[int, UUID] | None,
        limit: int,
    ) -> list[DomainTestCaseRevision]:
        items = self.revisions[test_case_id]
        if after is not None:
            items = [item for item in items if (item.version, item.id) > after]
        return items[:limit]


class MemoryChanges:
    def add(self, event: object) -> None:
        return None


class MemoryUnitOfWork:
    def __init__(self) -> None:
        self.projects = MemoryProjects()
        self.test_cases = MemoryTestCaseRepo()
        self.changes = MemoryChanges()

    def __enter__(self) -> "MemoryUnitOfWork":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def commit(self) -> None:
        return None


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    unit_of_work = MemoryUnitOfWork()
    ids = iter(
        [
            TEST_CASE_ID,
            REVISION_1_ID,
            EVENT_1_ID,
            REVISION_2_ID,
            EVENT_2_ID,
            *[UUID(int=value) for value in range(0x20, 0x40)],
        ]
    )
    service = Service(
        lambda: unit_of_work,
        ids=lambda: next(ids),
        clock=lambda: NOW,
        validate_document=validate_test_definition,
    )
    project_service = ProjectService(
        lambda: unit_of_work, ids=lambda: PROJECT_ID, clock=lambda: NOW
    )

    async def ready() -> bool:
        return True

    app = create_app(
        Settings(),
        database_probe=ready,
        tempo_probe=ready,
        project_service=project_service,
        test_case_service=service,
    )
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://testserver"
        ) as client,
    ):
        yield client


async def test_test_case_create_update_history_and_read_contract(
    client: httpx.AsyncClient,
) -> None:
    created = await client.post(
        f"/api/v1/projects/{PROJECT_ID}/test-cases",
        json={"name": "Probe", "definition": definition()},
    )
    assert created.status_code == 201
    assert created.headers["location"] == f"/api/v1/test-cases/{TEST_CASE_ID}"
    assert created.headers["etag"] == f'"test_case:{TEST_CASE_ID}:1"'
    assert created.json()["active_revision"]["version"] == 1

    fetched = await client.get(f"/api/v1/test-cases/{TEST_CASE_ID}")
    assert fetched.status_code == 200
    assert fetched.json() == created.json()

    updated_definition = definition("/healthz")
    updated = await client.put(
        f"/api/v1/test-cases/{TEST_CASE_ID}",
        headers={"If-Match": created.headers["etag"]},
        json={"name": "Probe", "definition": updated_definition},
    )
    assert updated.status_code == 200
    assert updated.headers["etag"] == f'"test_case:{TEST_CASE_ID}:2"'
    assert updated.json()["active_revision"]["version"] == 2
    assert (
        created.json()["active_revision"]["policy_fingerprint"]
        == updated.json()["active_revision"]["policy_fingerprint"]
    )

    history = await client.get(f"/api/v1/test-cases/{TEST_CASE_ID}/revisions")
    assert [item["version"] for item in history.json()["items"]] == [1, 2]

    stale = await client.put(
        f"/api/v1/test-cases/{TEST_CASE_ID}",
        headers={"If-Match": created.headers["etag"]},
        json={"name": "Stale", "definition": definition("/stale")},
    )
    assert stale.status_code == 412
    assert stale.json()["code"] == "revision_conflict"


async def test_test_case_validation_is_safe_and_cross_project_is_scoped(
    client: httpx.AsyncClient,
) -> None:
    invalid = await client.post(
        f"/api/v1/projects/{PROJECT_ID}/test-cases",
        json={
            "name": "Probe",
            "definition": {
                "request": {
                    "method": "GET",
                    "path": "/health",
                    "headers": [{"name": "Authorization", "value": "canary-secret-value"}],
                }
            },
        },
    )
    assert invalid.status_code == 422
    assert "canary-secret-value" not in invalid.text
    assert invalid.json()["code"] == "validation_failed"

    missing = await client.post(
        "/api/v1/projects/00000000-0000-4000-8000-000000000002/test-cases",
        json={"name": "Probe", "definition": definition()},
    )
    assert missing.status_code == 404


async def test_invalid_secret_reference_uses_the_stable_secret_problem(
    client: httpx.AsyncClient,
) -> None:
    invalid_definition = definition()
    invalid_definition["request"] = {
        "method": "GET",
        "path": "/health",
        "headers": [{"name": "Authorization", "value": {"$secret": "invalid-name"}}],
    }

    response = await client.post(
        f"/api/v1/projects/{PROJECT_ID}/test-cases",
        json={"name": "Probe", "definition": invalid_definition},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "secret_reference_invalid"
    assert response.json()["errors"][0]["code"] == "invalid_secret_reference"
    assert "invalid-name" not in response.text


async def test_replay_acknowledgement_without_opt_in_is_incompatible(
    client: httpx.AsyncClient,
) -> None:
    response = await client.post(
        f"/api/v1/projects/{PROJECT_ID}/test-cases",
        json={
            "name": "Probe",
            "definition": definition(),
            "unsafe_replay_acknowledgement": "duplicate_effects_possible",
        },
    )

    assert response.status_code == 422
    assert response.json()["errors"][0]["code"] == "incompatible_fields"


async def test_decimal_definition_tokens_preserve_exact_json_number_text(
    client: httpx.AsyncClient,
) -> None:
    response = await client.post(
        f"/api/v1/projects/{PROJECT_ID}/test-cases",
        content=(
            b'{"name":"Decimal probe","definition":{"request":{"method":"GET",'
            b'"path":"/health"},"assertions":[{"id":'
            b'"00000000-0000-4000-8000-000000000099","severity":"required",'
            b'"kind":"json_equals","pointer":"/amount",'
            b'"expected":0.123456789012345678901}]}}'
        ),
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 201
    assert b'"expected":0.123456789012345678901' in response.content


async def test_test_case_openapi_documents_m2_routes(client: httpx.AsyncClient) -> None:
    document = (await client.get("/openapi.json")).json()
    assert set(
        [
            "/api/v1/projects/{project_id}/test-cases",
            "/api/v1/test-cases/{test_case_id}",
            "/api/v1/test-cases/{test_case_id}/revisions",
        ]
    ) <= set(document["paths"])
    update = document["paths"]["/api/v1/test-cases/{test_case_id}"]["put"]
    if_match = next(item for item in update["parameters"] if item["name"] == "if-match")
    assert if_match["required"] is True
    assert "ETag" in update["responses"]["200"]["headers"]
    schemas = document["components"]["schemas"]
    assert schemas["TestCaseWrite"]["properties"]["definition"] == {
        "$ref": "#/components/schemas/TestDefinition"
    }
    assert schemas["TestCaseRevision"]["properties"]["definition"] == {
        "$ref": "#/components/schemas/CanonicalTestDefinition"
    }
    assert schemas["TestCaseRevision"]["properties"]["created_at"] == {
        "$ref": "#/components/schemas/Timestamp"
    }
    assert schemas["TestCaseRevisionPage"]["x-max-encoded-utf8-bytes"] == 1_048_576


async def test_valid_other_resource_etag_is_a_revision_conflict(
    client: httpx.AsyncClient,
) -> None:
    created = await client.post(
        f"/api/v1/projects/{PROJECT_ID}/test-cases",
        json={"name": "Probe", "definition": definition()},
    )
    assert created.status_code == 201

    response = await client.put(
        f"/api/v1/test-cases/{TEST_CASE_ID}",
        headers={"If-Match": f'"test_case:{PROJECT_ID}:1"'},
        json={"name": "Probe", "definition": definition("/changed")},
    )

    assert response.status_code == 412
    assert response.json()["code"] == "revision_conflict"
    history = await client.get(f"/api/v1/test-cases/{TEST_CASE_ID}/revisions")
    assert [item["version"] for item in history.json()["items"]] == [1]


async def test_revision_history_is_bounded_by_encoded_response_bytes(
    client: httpx.AsyncClient,
) -> None:
    large = definition()
    large["request"] = {
        "method": "POST",
        "path": "/write",
        "body": {"kind": "text", "value": "x" * 125_000},
    }
    large["assertions"] = [
        {
            "id": "00000000-0000-4000-8000-000000000099",
            "severity": "required",
            "kind": "text_equals",
            "expected": "y" * 125_000,
        }
    ]
    created = await client.post(
        f"/api/v1/projects/{PROJECT_ID}/test-cases",
        json={"name": "Large", "definition": large},
    )
    assert created.status_code == 201
    etag = created.headers["etag"]
    for version in range(2, 6):
        updated = await client.put(
            f"/api/v1/test-cases/{TEST_CASE_ID}",
            headers={"If-Match": etag},
            json={"name": f"Large {version}", "definition": large},
        )
        assert updated.status_code == 200
        etag = updated.headers["etag"]

    first = await client.get(f"/api/v1/test-cases/{TEST_CASE_ID}/revisions")

    assert first.status_code == 200
    assert len(first.content) <= 1_048_576
    assert first.json()["next_cursor"] is not None
    second = await client.get(
        f"/api/v1/test-cases/{TEST_CASE_ID}/revisions",
        params={"cursor": first.json()["next_cursor"]},
    )
    assert second.status_code == 200
    assert [item["version"] for item in first.json()["items"] + second.json()["items"]] == [
        1,
        2,
        3,
        4,
        5,
    ]

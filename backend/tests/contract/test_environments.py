from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import UUID

import httpx
import pytest

from sentinel.api.app import create_app
from sentinel.catalog.environments import Environment, EnvironmentService
from sentinel.catalog.projects import Project, ProjectService
from sentinel.config import Settings
from sentinel.security.definition_policy import validate_environment_document

PROJECT_ID = UUID("00000000-0000-4000-8000-000000000001")
ENVIRONMENT_ID = UUID("00000000-0000-4000-8000-000000000010")
REVISION_1_ID = UUID("00000000-0000-4000-8000-000000000011")
EVENT_1_ID = UUID("00000000-0000-4000-8000-000000000012")
REVISION_2_ID = UUID("00000000-0000-4000-8000-000000000013")
EVENT_2_ID = UUID("00000000-0000-4000-8000-000000000014")
NOW = datetime(2030, 1, 1, 12, 30, tzinfo=UTC)


class MemoryProjects:
    def __init__(self) -> None:
        self.items = {PROJECT_ID: Project(PROJECT_ID, "Synthetic", NOW, None, 1)}

    def add(self, project: Project) -> None:
        self.items[project.id] = project

    def get(self, project_id: UUID) -> Project | None:
        return self.items.get(project_id)

    def list_after(self, *, after: tuple[datetime, UUID] | None, limit: int) -> list[Project]:
        return list(self.items.values())[:limit]


class MemoryEnvironments:
    def __init__(self) -> None:
        self.items: dict[UUID, Environment] = {}

    def add(self, environment: Environment) -> None:
        self.items[environment.id] = environment

    def get(self, environment_id: UUID, *, for_update: bool = False) -> Environment | None:
        return self.items.get(environment_id)

    def replace(self, environment: Environment) -> None:
        self.items[environment.id] = environment

    def list_after(
        self,
        *,
        project_id: UUID,
        after: tuple[datetime, UUID] | None,
        limit: int,
    ) -> list[Environment]:
        items = sorted(self.items.values(), key=lambda item: (item.created_at, item.id))
        if after is not None:
            items = [item for item in items if (item.created_at, item.id) > after]
        return [item for item in items if item.project_id == project_id][:limit]


class MemoryChanges:
    def add(self, event: object) -> None:
        return None


class MemoryUnitOfWork:
    def __init__(self) -> None:
        self.projects = MemoryProjects()
        self.environments = MemoryEnvironments()
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
    ids = iter([ENVIRONMENT_ID, REVISION_1_ID, EVENT_1_ID, REVISION_2_ID, EVENT_2_ID])
    environment_service = EnvironmentService(
        lambda: unit_of_work,
        ids=lambda: next(ids),
        clock=lambda: NOW,
        validate_document=validate_environment_document,
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
        environment_service=environment_service,
    )
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://testserver"
        ) as http_client,
    ):
        yield http_client


async def test_environment_create_get_list_and_replace_contract(
    client: httpx.AsyncClient,
) -> None:
    created = await client.post(
        f"/api/v1/projects/{PROJECT_ID}/environments",
        json={
            "name": "Production",
            "definition": {
                "base_url": "HTTPS://Example.COM:443/api",
                "secret_references": [{"$secret": "SYNTHETIC_TOKEN"}],
            },
        },
    )

    assert created.status_code == 201
    assert created.headers["location"] == f"/api/v1/environments/{ENVIRONMENT_ID}"
    assert created.headers["etag"] == f'"environment:{ENVIRONMENT_ID}:1"'
    assert created.json()["active_revision"]["version"] == 1
    assert created.json()["active_revision"]["definition"]["base_url"] == "https://example.com/api/"
    assert "SYNTHETIC_TOKEN" in created.text

    listed = await client.get(f"/api/v1/projects/{PROJECT_ID}/environments")
    assert listed.status_code == 200
    assert listed.json()["items"][0]["active_revision_version"] == 1
    assert "etag" not in listed.headers

    fetched = await client.get(f"/api/v1/environments/{ENVIRONMENT_ID}")
    assert fetched.json() == created.json()
    assert fetched.headers["etag"] == created.headers["etag"]

    updated = await client.patch(
        f"/api/v1/environments/{ENVIRONMENT_ID}",
        headers={"If-Match": created.headers["etag"]},
        json={"definition": {"base_url": "https://v2.example"}},
    )
    assert updated.status_code == 200
    assert updated.headers["etag"] == f'"environment:{ENVIRONMENT_ID}:2"'
    assert updated.json()["active_revision"]["version"] == 2

    stale = await client.patch(
        f"/api/v1/environments/{ENVIRONMENT_ID}",
        headers={"If-Match": created.headers["etag"]},
        json={"name": "Stale"},
    )
    assert stale.status_code == 412
    assert stale.json()["code"] == "revision_conflict"


async def test_environment_update_requires_exact_strong_etag(
    client: httpx.AsyncClient,
) -> None:
    created = await client.post(
        f"/api/v1/projects/{PROJECT_ID}/environments",
        json={"name": "Production", "definition": {"base_url": "https://example.com"}},
    )
    assert created.status_code == 201

    missing = await client.patch(f"/api/v1/environments/{ENVIRONMENT_ID}", json={"name": "Changed"})
    assert missing.status_code == 428

    weak = await client.patch(
        f"/api/v1/environments/{ENVIRONMENT_ID}",
        headers={"If-Match": f'W/"environment:{ENVIRONMENT_ID}:1"'},
        json={"name": "Changed"},
    )
    assert weak.status_code == 422
    assert weak.json()["errors"][0]["pointer"] == "/if-match"


async def test_environment_validation_does_not_echo_secret_canary(
    client: httpx.AsyncClient,
) -> None:
    response = await client.post(
        f"/api/v1/projects/{PROJECT_ID}/environments",
        json={
            "name": "Production",
            "definition": {
                "base_url": "https://example.com",
                "variables": {"TOKEN": "{$secret:canary-secret-value}"},
            },
        },
    )

    assert response.status_code == 422
    assert "canary-secret-value" not in response.text

    invalid_name = await client.post(
        f"/api/v1/projects/{PROJECT_ID}/environments",
        json={
            "name": "bad\ncanary-secret-name",
            "definition": {"base_url": "https://example.com"},
        },
    )
    assert invalid_name.status_code == 422
    assert "canary-secret-name" not in invalid_name.text


async def test_environment_openapi_marks_if_match_required(client: httpx.AsyncClient) -> None:
    document = (await client.get("/openapi.json")).json()
    operation = document["paths"]["/api/v1/environments/{environment_id}"]["patch"]
    if_match = next(
        parameter
        for parameter in operation["parameters"]
        if parameter["in"] == "header" and parameter["name"] == "if-match"
    )

    assert if_match["required"] is True
    assert set(operation["responses"]) == {
        "200",
        "401",
        "403",
        "404",
        "409",
        "412",
        "413",
        "415",
        "422",
        "428",
        "500",
    }

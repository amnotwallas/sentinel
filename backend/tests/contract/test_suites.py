from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from types import TracebackType
from uuid import UUID

import httpx
import pytest

from sentinel.api.app import create_app
from sentinel.catalog.projects import Project, ProjectService
from sentinel.catalog.suites import Suite as DomainSuite
from sentinel.catalog.suites import SuiteService
from sentinel.catalog.suites import TestCaseRevisionReference as RevisionReference
from sentinel.config import Settings

PROJECT_ID = UUID("00000000-0000-4000-8000-000000000201")
SUITE_ID = UUID("00000000-0000-4000-8000-000000000210")
SUITE_REVISION_1_ID = UUID("00000000-0000-4000-8000-000000000211")
SUITE_EVENT_1_ID = UUID("00000000-0000-4000-8000-000000000212")
SUITE_REVISION_2_ID = UUID("00000000-0000-4000-8000-000000000213")
SUITE_EVENT_2_ID = UUID("00000000-0000-4000-8000-000000000214")
CASE_1_ID = UUID("00000000-0000-4000-8000-000000000221")
CASE_2_ID = UUID("00000000-0000-4000-8000-000000000222")
REVISION_1_ID = UUID("00000000-0000-4000-8000-000000000231")
REVISION_2_ID = UUID("00000000-0000-4000-8000-000000000232")
REVISION_3_ID = UUID("00000000-0000-4000-8000-000000000233")
NOW = datetime(2030, 1, 1, 12, 30, tzinfo=UTC)


class Projects:
    def __init__(self) -> None:
        self.items = {PROJECT_ID: Project(PROJECT_ID, "Synthetic", NOW, None, 1)}

    def add(self, project: Project) -> None:
        self.items[project.id] = project

    def get(self, project_id: UUID) -> Project | None:
        return self.items.get(project_id)

    def list_after(
        self,
        *,
        after: tuple[datetime, UUID] | None,
        limit: int,
    ) -> list[Project]:
        return list(self.items.values())[:limit]


class Suites:
    def __init__(self) -> None:
        self.items: dict[UUID, DomainSuite] = {}
        self.pins = {
            REVISION_1_ID: RevisionReference(CASE_1_ID, 3),
            REVISION_2_ID: RevisionReference(CASE_2_ID, 4),
        }

    def add(self, suite: DomainSuite) -> None:
        self.items[suite.id] = suite

    def get(self, suite_id: UUID, *, for_update: bool = False) -> DomainSuite | None:
        return self.items.get(suite_id)

    def replace(self, suite: DomainSuite) -> None:
        self.items[suite.id] = suite

    def list_after(
        self,
        *,
        project_id: UUID,
        after: tuple[datetime, UUID] | None,
        limit: int,
    ) -> list[DomainSuite]:
        return [suite for suite in self.items.values() if suite.project_id == project_id][:limit]

    def get_test_case_revision_for_project(
        self, project_id: UUID, revision_id: UUID
    ) -> RevisionReference | None:
        return self.pins.get(revision_id) if project_id == PROJECT_ID else None


class Changes:
    def add(self, event: object) -> None:
        return None


class UnitOfWork:
    def __init__(self) -> None:
        self.projects = Projects()
        self.suites = Suites()
        self.changes = Changes()

    def __enter__(self) -> UnitOfWork:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None

    def commit(self) -> None:
        return None


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    unit_of_work = UnitOfWork()
    ids = iter(
        [
            SUITE_ID,
            SUITE_REVISION_1_ID,
            SUITE_EVENT_1_ID,
            SUITE_REVISION_2_ID,
            SUITE_EVENT_2_ID,
        ]
    )
    suite_service = SuiteService(
        lambda: unit_of_work,
        ids=lambda: next(ids),
        clock=lambda: NOW,
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
        suite_service=suite_service,
    )
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://testserver"
        ) as client,
    ):
        yield client


async def test_suite_create_list_get_update_preserves_order_and_etags(
    client: httpx.AsyncClient,
) -> None:
    created = await client.post(
        f"/api/v1/projects/{PROJECT_ID}/suites",
        json={
            "name": "Ordered checks",
            "test_case_revision_ids": [str(REVISION_2_ID), str(REVISION_1_ID)],
        },
    )
    assert created.status_code == 201
    assert created.headers["location"] == f"/api/v1/suites/{SUITE_ID}"
    assert created.headers["etag"] == f'"suite:{SUITE_ID}:1"'
    assert [item["ordinal"] for item in created.json()["active_revision"]["items"]] == [0, 1]
    assert [
        item["test_case_revision_id"] for item in created.json()["active_revision"]["items"]
    ] == [str(REVISION_2_ID), str(REVISION_1_ID)]

    listed = await client.get(f"/api/v1/projects/{PROJECT_ID}/suites")
    assert listed.status_code == 200
    assert listed.json()["items"][0]["active_revision_version"] == 1

    fetched = await client.get(f"/api/v1/suites/{SUITE_ID}")
    assert fetched.status_code == 200
    assert fetched.json() == created.json()

    updated = await client.put(
        f"/api/v1/suites/{SUITE_ID}",
        headers={"If-Match": created.headers["etag"]},
        json={"name": "Updated checks", "test_case_revision_ids": [str(REVISION_1_ID)]},
    )
    assert updated.status_code == 200
    assert updated.headers["etag"] == f'"suite:{SUITE_ID}:2"'
    assert updated.json()["active_revision"]["version"] == 2
    assert updated.json()["active_revision"]["items"][0]["test_case_revision_id"] == str(
        REVISION_1_ID
    )

    stale = await client.put(
        f"/api/v1/suites/{SUITE_ID}",
        headers={"If-Match": created.headers["etag"]},
        json={"name": "Stale", "test_case_revision_ids": [str(REVISION_2_ID)]},
    )
    assert stale.status_code == 412
    assert stale.json()["code"] == "revision_conflict"


async def test_suite_rejects_duplicate_missing_and_invalid_etag_inputs(
    client: httpx.AsyncClient,
) -> None:
    duplicate = await client.post(
        f"/api/v1/projects/{PROJECT_ID}/suites",
        json={
            "name": "Duplicate",
            "test_case_revision_ids": [str(REVISION_1_ID), str(REVISION_1_ID)],
        },
    )
    assert duplicate.status_code == 422
    assert duplicate.json()["errors"][0]["code"] == "duplicate"

    missing = await client.post(
        f"/api/v1/projects/{PROJECT_ID}/suites",
        json={"name": "Missing", "test_case_revision_ids": [str(REVISION_3_ID)]},
    )
    assert missing.status_code == 404
    assert missing.json()["code"] == "resource_not_found"

    empty = await client.post(
        f"/api/v1/projects/{PROJECT_ID}/suites",
        json={"name": "Empty", "test_case_revision_ids": []},
    )
    assert empty.status_code == 422

    created = await client.post(
        f"/api/v1/projects/{PROJECT_ID}/suites",
        json={"name": "ETag", "test_case_revision_ids": [str(REVISION_1_ID)]},
    )
    malformed = await client.put(
        f"/api/v1/suites/{SUITE_ID}",
        headers={"If-Match": 'W/"suite:not-an-etag"'},
        json={"name": "Invalid", "test_case_revision_ids": [str(REVISION_1_ID)]},
    )
    assert created.status_code == 201
    assert malformed.status_code == 422
    assert malformed.json()["errors"][0]["location"] == "header"

    suite_id = created.json()["id"]
    write = {"name": "Invalid", "test_case_revision_ids": [str(REVISION_1_ID)]}
    missing_precondition = await client.put(f"/api/v1/suites/{suite_id}", json=write)
    wildcard = await client.put(f"/api/v1/suites/{suite_id}", headers={"If-Match": "*"}, json=write)
    multiple = await client.put(
        f"/api/v1/suites/{suite_id}",
        headers={"If-Match": f'"suite:{suite_id}:1", "suite:{suite_id}:2"'},
        json=write,
    )
    other_resource = await client.put(
        f"/api/v1/suites/{suite_id}",
        headers={"If-Match": f'"test_case:{suite_id}:1"'},
        json=write,
    )

    assert missing_precondition.status_code == 428
    assert missing_precondition.json()["code"] == "revision_precondition_required"
    assert wildcard.status_code == 422
    assert multiple.status_code == 422
    assert other_resource.status_code == 412
    assert other_resource.json()["code"] == "revision_conflict"


async def test_suite_openapi_documents_runtime_routes(client: httpx.AsyncClient) -> None:
    response = await client.get("/openapi.json")
    assert response.status_code == 200
    document = response.json()
    paths = document["paths"]
    assert "/api/v1/projects/{project_id}/suites" in paths
    assert "/api/v1/suites/{suite_id}" in paths
    assert paths["/api/v1/suites/{suite_id}"]["put"]["parameters"][-1]["required"] is True
    schemas = document["components"]["schemas"]
    assert schemas["SuiteWrite"]["properties"]["name"] == {"$ref": "#/components/schemas/Name"}
    assert schemas["SuiteRevision"]["properties"]["created_at"] == {
        "$ref": "#/components/schemas/Timestamp"
    }
    assert schemas["SuiteRevisionItem"]["properties"]["test_case_revision_id"] == {
        "$ref": "#/components/schemas/UUID"
    }
    assert schemas["SuitePage"]["x-max-encoded-utf8-bytes"] == 1_048_576

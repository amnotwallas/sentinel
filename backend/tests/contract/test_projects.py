import base64
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import UUID

import httpx
import pytest
from pydantic import SecretStr

from sentinel.api.app import create_app
from sentinel.catalog.projects import Project, ProjectNameConflict, ProjectService
from sentinel.config import Settings

IDS = [
    UUID("00000000-0000-4000-8000-000000000001"),
    UUID("00000000-0000-4000-8000-000000000002"),
    UUID("00000000-0000-4000-8000-000000000003"),
]
NOW = datetime(2030, 1, 1, 12, 30, tzinfo=UTC)


class MemoryProjects:
    def __init__(self) -> None:
        self.items: dict[UUID, Project] = {}

    def add(self, project: Project) -> None:
        if any(existing.name == project.name for existing in self.items.values()):
            raise ProjectNameConflict
        self.items[project.id] = project

    def get(self, project_id: UUID) -> Project | None:
        return self.items.get(project_id)

    def list_after(
        self,
        *,
        after: tuple[datetime, UUID] | None,
        limit: int,
    ) -> list[Project]:
        projects = sorted(self.items.values(), key=lambda item: (item.created_at, item.id))
        if after is not None:
            projects = [project for project in projects if (project.created_at, project.id) > after]
        return projects[:limit]


class MemoryUnitOfWork:
    def __init__(self, projects: MemoryProjects) -> None:
        self.projects = projects

    def __enter__(self) -> "MemoryUnitOfWork":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def commit(self) -> None:
        return None


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    projects = MemoryProjects()
    ids = iter(IDS)
    service = ProjectService(
        lambda: MemoryUnitOfWork(projects),
        ids=lambda: next(ids),
        clock=lambda: NOW,
    )

    async def database() -> bool:
        return True

    async def tempo() -> bool:
        return False

    app = create_app(
        Settings(),
        database_probe=database,
        tempo_probe=tempo,
        project_service=service,
    )
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://testserver"
        ) as http_client,
    ):
        yield http_client


async def test_create_and_get_project_return_exact_contract_headers(
    client: httpx.AsyncClient,
) -> None:
    created = await client.post("/api/v1/projects", json={"name": "Synthetic project"})

    assert created.status_code == 201
    assert created.json() == {
        "id": str(IDS[0]),
        "name": "Synthetic project",
        "created_at": "2030-01-01T12:30:00.000000Z",
        "deleted_at": None,
    }
    assert created.headers["location"] == f"/api/v1/projects/{IDS[0]}"
    assert created.headers["etag"] == f'"project:{IDS[0]}:1"'

    fetched = await client.get(f"/api/v1/projects/{IDS[0]}")
    assert fetched.status_code == 200
    assert fetched.json() == created.json()
    assert fetched.headers["etag"] == created.headers["etag"]


async def test_project_list_uses_opaque_cursor_without_an_etag(
    client: httpx.AsyncClient,
) -> None:
    for name in ("First", "Second", "Third"):
        assert (await client.post("/api/v1/projects", json={"name": name})).status_code == 201

    first_page = await client.get("/api/v1/projects", params={"limit": 2})
    assert first_page.status_code == 200
    assert [item["name"] for item in first_page.json()["items"]] == ["First", "Second"]
    cursor = first_page.json()["next_cursor"]
    assert isinstance(cursor, str) and cursor
    assert "etag" not in first_page.headers

    second_page = await client.get("/api/v1/projects", params={"limit": 2, "cursor": cursor})
    assert second_page.status_code == 200
    assert [item["name"] for item in second_page.json()["items"]] == ["Third"]
    assert second_page.json()["next_cursor"] is None


async def test_project_cursor_rejects_duplicate_json_keys(client: httpx.AsyncClient) -> None:
    for name in ("First", "Second"):
        assert (await client.post("/api/v1/projects", json={"name": name})).status_code == 201
    response = await client.get("/api/v1/projects", params={"limit": 1})
    cursor = response.json()["next_cursor"]
    assert isinstance(cursor, str)
    decoded = base64.urlsafe_b64decode(cursor + ("=" * (-len(cursor) % 4))).decode("utf-8")
    duplicated = decoded.replace(
        '"resource_kind":"projects"',
        '"resource_kind":"wrong","resource_kind":"projects"',
    )
    malicious = base64.urlsafe_b64encode(duplicated.encode()).rstrip(b"=").decode()

    rejected = await client.get("/api/v1/projects", params={"cursor": malicious})

    assert rejected.status_code == 422
    assert rejected.json()["errors"][0]["code"] == "cursor_invalid"


async def test_project_cursor_rejects_noncanonical_timestamp(client: httpx.AsyncClient) -> None:
    for name in ("First", "Second"):
        assert (await client.post("/api/v1/projects", json={"name": name})).status_code == 201
    response = await client.get("/api/v1/projects", params={"limit": 1})
    cursor = response.json()["next_cursor"]
    assert isinstance(cursor, str)
    decoded = base64.urlsafe_b64decode(cursor + ("=" * (-len(cursor) % 4))).decode("utf-8")
    noncanonical = decoded.replace("2030-01-01T12:30", "2030-1-1T12:30")
    malicious = base64.urlsafe_b64encode(noncanonical.encode()).rstrip(b"=").decode()

    rejected = await client.get("/api/v1/projects", params={"cursor": malicious})

    assert rejected.status_code == 422
    assert rejected.json()["errors"][0]["code"] == "cursor_invalid"


async def test_duplicate_name_returns_safe_resource_conflict(
    client: httpx.AsyncClient,
) -> None:
    assert (await client.post("/api/v1/projects", json={"name": "Duplicate"})).status_code == 201

    response = await client.post("/api/v1/projects", json={"name": "Duplicate"})

    assert response.status_code == 409
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json() == {
        "type": "urn:sentinel:problem:resource_conflict",
        "title": "Resource conflict",
        "status": 409,
        "code": "resource_conflict",
    }


@pytest.mark.parametrize(
    ("request_path", "params"),
    [
        ("/api/v1/projects/not-a-uuid", None),
        ("/api/v1/projects", {"limit": 0}),
        ("/api/v1/projects", {"cursor": "not-a-cursor"}),
        ("/api/v1/projects", {"unexpected": "canary-secret"}),
    ],
)
async def test_invalid_path_or_query_returns_bounded_safe_errors(
    client: httpx.AsyncClient,
    request_path: str,
    params: dict[str, str | int] | None,
) -> None:
    response = await client.get(request_path, params=params)

    assert response.status_code == 422
    assert response.json()["code"] == "validation_failed"
    assert 1 <= len(response.json()["errors"]) <= 50
    assert "canary-secret" not in response.text


async def test_invalid_create_body_never_echoes_submitted_values(
    client: httpx.AsyncClient,
) -> None:
    response = await client.post(
        "/api/v1/projects",
        json={"name": "bad\ncanary-secret", "unknown-canary-secret": True},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "validation_failed"
    assert {error["pointer"] for error in response.json()["errors"]} == {"/*", "/name"}
    assert "canary-secret" not in response.text


@pytest.mark.parametrize(
    "body",
    [
        b'{"name":"First","name":"Second"}',
        b'{"name":NaN}',
        b'{"name":"\\ud800"}',
        b'{"name":"\xff"}',
    ],
)
async def test_invalid_json_tokens_are_rejected_before_domain_processing(
    client: httpx.AsyncClient, body: bytes
) -> None:
    response = await client.post(
        "/api/v1/projects", content=body, headers={"content-type": "application/json"}
    )

    assert response.status_code == 422
    assert response.json()["code"] == "validation_failed"
    assert (await client.get("/api/v1/projects")).json()["items"] == []


@pytest.mark.parametrize(
    "body",
    [
        b'{"name":' + (b"1" * 5_000) + b"}",
        b'{"name":' + (b"[" * 2_000) + (b"]" * 2_000) + b"}",
    ],
)
async def test_pathological_json_is_a_bounded_problem_response(
    client: httpx.AsyncClient, body: bytes
) -> None:
    response = await client.post(
        "/api/v1/projects", content=body, headers={"content-type": "application/json"}
    )

    assert response.status_code == 422
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["code"] == "validation_failed"


async def test_create_and_detail_reject_unexpected_query_fields(
    client: httpx.AsyncClient,
) -> None:
    created = await client.post(
        "/api/v1/projects",
        params={"unexpected": "canary-secret"},
        json={"name": "Synthetic project"},
    )
    missing = await client.get(f"/api/v1/projects/{IDS[0]}", params={"unexpected": "canary-secret"})

    for response in (created, missing):
        assert response.status_code == 422
        assert response.json()["errors"][0]["code"] == "extra_field"
        assert "canary-secret" not in response.text
    assert (await client.get("/api/v1/projects")).json()["items"] == []


async def test_create_rejects_if_match_without_writing(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/api/v1/projects",
        headers={"if-match": f'"project:{IDS[0]}:1"'},
        json={"name": "Synthetic project"},
    )

    assert response.status_code == 422
    assert response.json()["errors"] == [
        {
            "location": "header",
            "pointer": "/if-match",
            "code": "incompatible_fields",
            "message": "Incompatible fields",
        }
    ]
    assert (await client.get("/api/v1/projects")).json()["items"] == []


async def test_missing_project_is_indistinguishable_from_other_missing_resources(
    client: httpx.AsyncClient,
) -> None:
    response = await client.get(f"/api/v1/projects/{IDS[0]}")

    assert response.status_code == 404
    assert response.json()["code"] == "resource_not_found"
    assert response.json()["title"] == "Request failed"


async def test_create_requires_json_and_enforces_body_limit(client: httpx.AsyncClient) -> None:
    wrong_type = await client.post(
        "/api/v1/projects",
        content=b"name=Synthetic",
        headers={"content-type": "application/x-www-form-urlencoded"},
    )
    assert wrong_type.status_code == 415
    assert wrong_type.json()["code"] == "unsupported_media_type"

    oversized = await client.post(
        "/api/v1/projects",
        content=b'{"name":"' + (b"x" * 524_289) + b'"}',
        headers={"content-type": "application/json"},
    )
    assert oversized.status_code == 413
    assert oversized.json()["code"] == "request_too_large"

    declared_oversized = await client.post(
        "/api/v1/projects",
        content=b"{}",
        headers={"content-type": "application/json", "content-length": "524289"},
    )
    assert declared_oversized.status_code == 413
    assert declared_oversized.json()["code"] == "request_too_large"

    async def chunked_body() -> AsyncIterator[bytes]:
        yield b'{"name":"' + (b"x" * 300_000)
        yield b"x" * 300_000
        raise AssertionError("body reader continued after crossing the limit")

    chunked = await client.post(
        "/api/v1/projects",
        content=chunked_body(),
        headers={"content-type": "application/json"},
    )
    assert chunked.status_code == 413
    assert chunked.json()["code"] == "request_too_large"


async def test_authentication_is_checked_before_the_request_body_is_read() -> None:
    app = create_app(Settings(api_host="0.0.0.0", api_token=SecretStr("canary-token")))

    async def unread_body() -> AsyncIterator[bytes]:
        raise AssertionError("unauthenticated request body was consumed")
        yield b""  # pragma: no cover - makes this an async generator

    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://testserver"
        ) as protected_client,
    ):
        response = await protected_client.post(
            "/api/v1/projects",
            content=unread_body(),
            headers={"content-type": "application/json"},
        )

    assert response.status_code == 401
    assert response.json()["code"] == "authentication_required"


async def test_runtime_openapi_publishes_only_the_implemented_project_slice(
    client: httpx.AsyncClient,
) -> None:
    document = (await client.get("/openapi.json")).json()

    assert set(document["paths"]["/api/v1/projects"]) == {"get", "post"}
    assert set(document["paths"]["/api/v1/projects/{project_id}"]) == {"get"}
    assert document["paths"]["/api/v1/projects"]["post"]["operationId"] == "create_project"
    assert document["paths"]["/api/v1/projects"]["post"].get("parameters", []) == []
    assert document["paths"]["/api/v1/projects"]["get"]["operationId"] == "list_projects"
    assert document["paths"]["/api/v1/projects/{project_id}"]["get"]["operationId"] == (
        "get_project"
    )
    assert {"Project", "ProjectCreate", "ProjectPage"} <= set(document["components"]["schemas"])
    project_schema = document["components"]["schemas"]["Project"]
    assert project_schema["properties"]["id"]["format"] == "uuid"
    assert project_schema["properties"]["created_at"]["format"] == "date-time"
    name_schema = document["components"]["schemas"]["ProjectCreate"]["properties"]["name"]
    assert (name_schema["minLength"], name_schema["maxLength"]) == (1, 120)
    problem_schema = document["components"]["schemas"]["Problem"]
    assert problem_schema["properties"]["errors"]["type"] == "array"
    assert problem_schema["properties"]["errors"]["minItems"] == 1
    assert problem_schema["properties"]["errors"]["maxItems"] == 50
    assert "errors" not in problem_schema["required"]
    page_schema = document["components"]["schemas"]["ProjectPage"]
    assert set(page_schema["required"]) == {"items", "next_cursor"}
    assert "resource_conflict" in problem_schema["properties"]["code"]["enum"]
    create_responses = document["paths"]["/api/v1/projects"]["post"]["responses"]
    assert set(create_responses) == {
        "201",
        "401",
        "403",
        "404",
        "409",
        "413",
        "415",
        "422",
        "500",
    }
    assert set(create_responses["201"]["headers"]) == {"ETag", "Location"}
    for status in {"401", "403", "404", "409", "413", "415", "422", "500"}:
        assert set(create_responses[status]["content"]) == {"application/problem+json"}
        assert create_responses[status]["content"]["application/problem+json"]["schema"] == {
            "$ref": "#/components/schemas/Problem"
        }
    list_responses = document["paths"]["/api/v1/projects"]["get"]["responses"]
    assert set(list_responses) == {"200", "401", "403", "404", "422", "500"}
    get_responses = document["paths"]["/api/v1/projects/{project_id}"]["get"]["responses"]
    assert set(get_responses) == {"200", "401", "403", "404", "422", "500"}
    assert set(get_responses["200"]["headers"]) == {"ETag"}
    assert "Problem" in document["components"]["schemas"]
    assert "/api/v1/projects/{project_id}/environments" not in document["paths"]


async def test_runtime_openapi_problem_schema_enforces_exact_safe_variants(
    client: httpx.AsyncClient,
) -> None:
    document = (await client.get("/openapi.json")).json()
    problem_schema = document["components"]["schemas"]["Problem"]

    variants = {}
    for variant in problem_schema["oneOf"]:
        variants[variant["properties"]["code"]["const"]] = variant

    assert variants["validation_failed"]["properties"] == {
        "code": {"const": "validation_failed"},
        "status": {"const": 422},
        "title": {"const": "Request validation failed"},
        "type": {"const": "urn:sentinel:problem:validation_failed"},
    }
    assert variants["resource_conflict"] == {
        "not": {"required": ["errors"]},
        "properties": {
            "code": {"const": "resource_conflict"},
            "status": {"const": 409},
            "title": {"const": "Resource conflict"},
            "type": {"const": "urn:sentinel:problem:resource_conflict"},
        },
    }

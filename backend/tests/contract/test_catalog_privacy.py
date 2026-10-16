import ast
import json
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest

from sentinel.api.app import create_app
from sentinel.config import Settings

_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_PLANNED = json.loads(
    (_REPOSITORY_ROOT / "docs/contracts/milestone-2.openapi.json").read_text(encoding="utf-8")
)


def test_catalog_runtime_layers_have_no_target_io_or_secret_resolution_imports() -> None:
    source_root = _REPOSITORY_ROOT / "backend/src/sentinel"
    paths = [
        *(source_root / "catalog").glob("*.py"),
        *(source_root / "api/catalog").glob("*.py"),
        *(source_root / "persistence/catalog").glob("*.py"),
        source_root / "security/definition_policy.py",
    ]
    forbidden_modules = {
        "httpx",
        "requests",
        "socket",
        "urllib.request",
        "sentinel.execution",
        "sentinel.security.secret_resolution",
        "sentinel.security.secrets",
        "sentinel.worker",
    }

    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imported = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        imported.update(
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module is not None
        )
        assert not {
            module
            for module in imported
            if any(
                module == forbidden or module.startswith(f"{forbidden}.")
                for forbidden in forbidden_modules
            )
        }, path


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    async def ready() -> bool:
        return True

    app = create_app(Settings(), database_probe=ready, tempo_probe=ready)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://testserver"
        ) as http_client,
    ):
        yield http_client


async def test_runtime_catalog_schemas_match_accepted_project_and_environment_contracts(
    client: httpx.AsyncClient,
) -> None:
    runtime = (await client.get("/openapi.json")).json()
    component_names = {
        "CIDR",
        "CanonicalEnvironmentDocument",
        "CanonicalTargetPolicy",
        "Cursor",
        "EnvironmentCreate",
        "EnvironmentDetail",
        "EnvironmentDocument",
        "EnvironmentPage",
        "EnvironmentPatch",
        "EnvironmentRevision",
        "EnvironmentSummary",
        "Hostname",
        "Name",
        "Project",
        "ProjectCreate",
        "ProjectPage",
        "SecretName",
        "SecretReference",
        "TargetPolicy",
        "Timestamp",
        "UUID",
        "VariableName",
        "Version",
    }

    runtime_schemas = runtime["components"]["schemas"]
    planned_schemas = _PLANNED["components"]["schemas"]
    assert {name: runtime_schemas.get(name) for name in component_names} == {
        name: planned_schemas[name] for name in component_names
    }

import sys
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from pydantic import SecretStr
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

import sentinel.api.app as app_module
from sentinel.api.app import create_app
from sentinel.config import Settings

pytestmark = pytest.mark.integration


@pytest.fixture
def revision_table(engine: Engine) -> Iterator[Engine]:
    # The shared engine fixture guards the dedicated *_test PostgreSQL database.
    with engine.connect() as connection:
        original = list(connection.scalars(text("SELECT version_num FROM alembic_version")))
    try:
        yield engine
    finally:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "CREATE TABLE IF NOT EXISTS alembic_version "
                    "(version_num VARCHAR(32) PRIMARY KEY)"
                )
            )
            connection.execute(text("DELETE FROM alembic_version"))
            for revision in original:
                connection.execute(
                    text("INSERT INTO alembic_version VALUES (:revision)"), {"revision": revision}
                )


@pytest.fixture
async def client(revision_table: Engine) -> AsyncIterator[httpx.AsyncClient]:
    async def tempo() -> bool:
        return False

    app = create_app(
        Settings(
            database_url=SecretStr(revision_table.url.render_as_string(hide_password=False)),
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
        yield client


@pytest.fixture
def next_migration(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, revision_table: Engine) -> Path:
    with revision_table.connect() as connection:
        heads = list(connection.scalars(text("SELECT version_num FROM alembic_version")))
    assert len(heads) == 1
    current_head = heads[0]
    versions = tmp_path / "versions"
    versions.mkdir()
    (versions / "current.py").write_text(f"revision = {current_head!r}\ndown_revision = None\n")
    (versions / "next.py").write_text(
        f"revision = 'readiness_next'\ndown_revision = {current_head!r}\n"
    )
    (tmp_path / "env.py").write_text(
        "from pathlib import Path\n"
        "Path(__file__).with_name('migration_ran').write_text('unexpected')\n"
        "raise AssertionError('readiness must not execute migrations')\n"
    )

    def scripts(_: Config) -> ScriptDirectory:
        return ScriptDirectory(str(tmp_path))

    # Supply real Alembic migration assets without adding a production migration.
    monkeypatch.setattr(ScriptDirectory, "from_config", staticmethod(scripts))
    return versions


async def test_current_packaged_head_is_ready_from_another_working_directory(
    client: httpx.AsyncClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    response = await client.get("/health/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready", "postgres": "available", "tempo": "unavailable"}


async def test_repeated_readiness_probes_do_not_mutate_import_paths(
    client: httpx.AsyncClient,
) -> None:
    original = sys.path.copy()
    try:
        for _ in range(5):
            assert (await client.get("/health/ready")).status_code == 200
        assert sys.path == original
    finally:
        sys.path[:] = original


async def test_unmigrated_database_is_not_ready_and_is_not_migrated(
    client: httpx.AsyncClient, revision_table: Engine
) -> None:
    with revision_table.begin() as connection:
        connection.execute(text("DROP TABLE alembic_version"))
    response = await client.get("/health/ready")
    assert response.status_code == 503
    assert response.json()["postgres"] == "unavailable"
    with revision_table.connect() as connection:
        assert connection.scalar(text("SELECT to_regclass('alembic_version')")) is None


async def test_empty_revision_table_is_not_ready(
    client: httpx.AsyncClient, revision_table: Engine
) -> None:
    with revision_table.begin() as connection:
        connection.execute(text("DELETE FROM alembic_version"))
    assert (await client.get("/health/ready")).status_code == 503
    with revision_table.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM alembic_version")) == 0


async def test_pending_migration_is_not_ready_and_does_not_upgrade(
    client: httpx.AsyncClient, revision_table: Engine, next_migration: Path
) -> None:
    with revision_table.connect() as connection:
        original = list(connection.scalars(text("SELECT version_num FROM alembic_version")))
    assert (await client.get("/health/ready")).status_code == 503
    with revision_table.connect() as connection:
        assert list(connection.scalars(text("SELECT version_num FROM alembic_version"))) == original
    assert not (next_migration.parent / "migration_ran").exists()


async def test_new_expected_head_is_ready_without_changing_probe_code(
    client: httpx.AsyncClient, revision_table: Engine, next_migration: Path
) -> None:
    with revision_table.begin() as connection:
        connection.execute(text("UPDATE alembic_version SET version_num = 'readiness_next'"))
    assert (await client.get("/health/ready")).status_code == 200
    assert not (next_migration.parent / "migration_ran").exists()


async def test_startup_with_empty_postgresql_schema_does_not_migrate(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    # An empty, task-owned schema exercises startup without application/version tables.
    schema = f"readiness_{uuid4().hex}"
    with engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    isolated = create_engine(
        engine.url,
        hide_parameters=True,
        connect_args={"options": f"-c search_path={schema}"},
    )

    def database(_: str) -> tuple[Engine, sessionmaker[Session]]:
        return isolated, sessionmaker(isolated)

    async def tempo() -> bool:
        return False

    monkeypatch.setattr(app_module, "create_database", database)
    try:
        app = create_app(Settings(otlp_endpoint=None), tempo_probe=tempo)
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app), base_url="http://testserver"
            ) as empty_client,
        ):
            assert (await empty_client.get("/health/live")).status_code == 200
            assert (await empty_client.get("/health/ready")).status_code == 503
            with isolated.connect() as connection:
                assert inspect(connection).get_table_names() == []
    finally:
        isolated.dispose()
        with engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))


async def test_unknown_database_revision_is_not_ready(
    client: httpx.AsyncClient, revision_table: Engine
) -> None:
    with revision_table.begin() as connection:
        connection.execute(text("UPDATE alembic_version SET version_num = 'unknown'"))
    assert (await client.get("/health/ready")).status_code == 503


async def test_multiple_migration_heads_fail_closed(
    client: httpx.AsyncClient, revision_table: Engine, next_migration: Path
) -> None:
    with revision_table.connect() as connection:
        current_head = connection.scalar(text("SELECT version_num FROM alembic_version"))
    (next_migration / "other.py").write_text(
        f"revision = 'readiness_other'\ndown_revision = {current_head!r}\n"
    )
    with revision_table.begin() as connection:
        connection.execute(text("UPDATE alembic_version SET version_num = 'readiness_next'"))
        connection.execute(text("INSERT INTO alembic_version VALUES ('readiness_other')"))
    assert (await client.get("/health/ready")).status_code == 503


async def test_missing_migration_assets_fail_closed(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def missing(_: Config) -> ScriptDirectory:
        raise FileNotFoundError("synthetic-private-path")

    monkeypatch.setattr(ScriptDirectory, "from_config", staticmethod(missing))
    response = await client.get("/health/ready")
    assert response.status_code == 503
    assert "synthetic-private-path" not in response.text

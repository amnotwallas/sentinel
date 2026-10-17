from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest
from alembic.command import downgrade, upgrade
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

pytestmark = pytest.mark.integration


def test_m3_01_migration_round_trip_preserves_legacy_execution(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = engine.url.render_as_string(hide_password=False)
    monkeypatch.setenv("SENTINEL_DATABASE_URL", database_url)
    config = Config(str(Path(__file__).parents[2] / "alembic.ini"))

    downgrade(config, "0006")
    legacy_id = UUID("50000000-0000-4000-8000-000000000001")
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO executions "
                "(id,status,verdict,created_at,started_at,finished_at) "
                "VALUES (:id,'queued',NULL,now(),NULL,NULL)"
            ),
            {"id": legacy_id},
        )
    upgrade(config, "head")
    columns = {column["name"] for column in inspect(engine).get_columns("executions")}
    assert {"project_id", "environment_id", "source_revision_id"} <= columns
    with engine.connect() as connection:
        assert (
            connection.scalar(
                text("SELECT project_id FROM executions WHERE id = :id"), {"id": legacy_id}
            )
            is None
        )
    assert inspect(engine).has_table("execution_items")
    assert inspect(engine).has_table("execution_idempotency")

    with engine.begin() as connection:
        connection.execute(
            text("UPDATE executions SET verdict = 'passed' WHERE id = :id"),
            {"id": legacy_id},
        )
    downgrade(config, "0006")
    with engine.connect() as connection:
        assert (
            connection.scalar(text("SELECT id FROM executions WHERE id = :id"), {"id": legacy_id})
            == legacy_id
        )
        assert (
            connection.scalar(
                text("SELECT verdict FROM executions WHERE id = :id"), {"id": legacy_id}
            )
            == "not_evaluated"
        )
    upgrade(config, "head")

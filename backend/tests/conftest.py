import os
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, delete, make_url, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from sentinel.persistence.database import deserialize_json, serialize_json
from sentinel.persistence.models import (
    ChangeEventRow,
    EnvironmentRevisionRow,
    EnvironmentRow,
    ExecutionRow,
    JobRow,
    ProjectRow,
    SuiteRevisionItemRow,
    SuiteRevisionRow,
    SuiteRow,
    TestCaseRevisionRow,
    TestCaseRow,
)
from sentinel.persistence.queue import PostgresJobStore


@dataclass
class Clock:
    value: datetime = datetime(2030, 1, 1, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.value

    def advance(self, seconds: int) -> None:
        self.value += timedelta(seconds=seconds)


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def engine() -> Iterator[Engine]:
    url = os.getenv("SENTINEL_TEST_DATABASE_URL")
    if not url:
        pytest.fail("Set SENTINEL_TEST_DATABASE_URL to a migrated PostgreSQL *_test database")
    parsed = make_url(url)
    if parsed.drivername != "postgresql+psycopg" or not (parsed.database or "").endswith("_test"):
        pytest.fail("Integration tests require a dedicated postgresql+psycopg *_test database")
    engine = create_engine(
        url,
        pool_pre_ping=True,
        hide_parameters=True,
        json_serializer=serialize_json,
        json_deserializer=deserialize_json,
    )
    with engine.begin() as conn:
        conn.execute(text("SET CONSTRAINTS fk_environments_active_revision DEFERRED"))
        conn.execute(delete(JobRow))
        conn.execute(delete(ExecutionRow))
        conn.execute(delete(ChangeEventRow))
        conn.execute(delete(SuiteRevisionItemRow))
        conn.execute(delete(SuiteRevisionRow))
        conn.execute(delete(SuiteRow))
        conn.execute(delete(TestCaseRevisionRow))
        conn.execute(delete(TestCaseRow))
        conn.execute(delete(EnvironmentRevisionRow))
        conn.execute(delete(EnvironmentRow))
        conn.execute(delete(ProjectRow))
    yield engine
    engine.dispose()


@pytest.fixture
def store(engine: Engine, clock: Clock) -> PostgresJobStore:
    return PostgresJobStore(sessionmaker(engine, expire_on_commit=False), clock=clock)

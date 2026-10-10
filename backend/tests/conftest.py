import os
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, delete, make_url
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from sentinel.persistence.models import ExecutionRow, JobRow
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
    engine = create_engine(url, pool_pre_ping=True, hide_parameters=True)
    with engine.begin() as conn:
        conn.execute(delete(JobRow))
        conn.execute(delete(ExecutionRow))
    yield engine
    engine.dispose()


@pytest.fixture
def store(engine: Engine, clock: Clock) -> PostgresJobStore:
    return PostgresJobStore(sessionmaker(engine, expire_on_commit=False), clock=clock)

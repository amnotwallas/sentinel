from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

import pytest
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from sentinel.execution.domain import InfrastructureFailure, Lease
from sentinel.persistence.orchestration import PostgresOrchestrationStore


class BrokenSessions:
    @contextmanager
    def begin(self) -> Iterator[Session]:
        raise OperationalError(
            "SELECT synthetic-sensitive-detail",
            {},
            RuntimeError("synthetic-sensitive-detail"),
        )
        yield cast(Session, object())


def test_database_operational_error_is_sanitized_as_retryable_infrastructure_failure() -> None:
    store = PostgresOrchestrationStore(cast(sessionmaker[Session], BrokenSessions()))
    lease = Lease(
        UUID("70000000-0000-4000-8000-000000000001"),
        UUID("70000000-0000-4000-8000-000000000002"),
        "execute_execution",
        UUID("70000000-0000-4000-8000-000000000003"),
        UUID("70000000-0000-4000-8000-000000000004"),
        datetime(2030, 1, 1, tzinfo=UTC),
        1,
    )

    with pytest.raises(InfrastructureFailure) as captured:
        store.complete_execution(lease)

    assert str(captured.value) == "database_operation_failed"
    assert "synthetic-sensitive-detail" not in str(captured.value)

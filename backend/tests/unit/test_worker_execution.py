from __future__ import annotations

from datetime import UTC, datetime
from typing import cast
from uuid import UUID

from opentelemetry.sdk.trace import TracerProvider
from pydantic import SecretStr
from sqlalchemy.orm import Session, sessionmaker

from sentinel.config import Settings
from sentinel.execution.domain import Lease
from sentinel.execution.orchestration import ExecutionOrchestrator
from sentinel.persistence.orchestration import PostgresOrchestrationStore
from sentinel.security.secrets import EnvironmentSecretResolver
from sentinel.telemetry.execution import OpenTelemetryTraceLifecycle
from sentinel.transport.http import HTTPTransportAdapter
from sentinel.worker.execution import build_execution_orchestrator, execution_handler
from sentinel.worker.runtime import HandlerCompletion, WorkerCancellation

LEASE = Lease(
    UUID("20000000-0000-4000-8000-000000000001"),
    UUID("20000000-0000-4000-8000-000000000002"),
    "execute_execution",
    UUID("20000000-0000-4000-8000-000000000003"),
    UUID("20000000-0000-4000-8000-000000000004"),
    datetime(2030, 1, 1, tzinfo=UTC),
    1,
)


async def test_execution_handler_runs_orchestrator_and_owns_job_completion() -> None:
    class RecordingOrchestrator:
        def __init__(self) -> None:
            self.calls: list[tuple[Lease, WorkerCancellation]] = []

        def run(self, lease: Lease, cancellation: WorkerCancellation) -> None:
            self.calls.append((lease, cancellation))

    orchestrator = RecordingOrchestrator()
    cancellation = WorkerCancellation()

    result = await execution_handler(cast(ExecutionOrchestrator, orchestrator))(LEASE, cancellation)

    assert result == HandlerCompletion.DURABLY_COMPLETED
    assert orchestrator.calls == [(LEASE, cancellation)]


def test_runtime_composition_uses_frozen_execution_security_adapters() -> None:
    sessions = cast(sessionmaker[Session], object())
    settings = Settings(
        database_url=SecretStr("postgresql+psycopg://sentinel:test@127.0.0.1/sentinel")
    )
    tracer = TracerProvider().get_tracer("sentinel.test.worker")

    orchestrator = build_execution_orchestrator(sessions, settings, tracer)

    assert isinstance(orchestrator.store, PostgresOrchestrationStore)
    assert isinstance(orchestrator.transport, HTTPTransportAdapter)
    assert isinstance(orchestrator.secrets_resolver, EnvironmentSecretResolver)
    assert isinstance(orchestrator.traces, OpenTelemetryTraceLifecycle)

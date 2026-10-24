from __future__ import annotations

import asyncio
from collections.abc import Sequence
from threading import Event
from typing import cast
from uuid import uuid4

import pytest
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExporter, SpanExportResult
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from sentinel.execution.domain import Lease
from sentinel.execution.orchestration import ExecutionOrchestrator
from sentinel.execution.ports import NO_CANCELLATION, CancellationSignal, TransportResult
from sentinel.execution.preparation import PreparedRequest
from sentinel.execution.service import WorkService
from sentinel.persistence.models import ExecutionRow, JobRow, ResponseArtifactRow, TestAttemptRow
from sentinel.persistence.orchestration import PostgresOrchestrationStore
from sentinel.security.secrets import EnvironmentSecretResolver
from sentinel.telemetry.execution import OpenTelemetryTraceLifecycle
from sentinel.worker.execution import execution_handler
from sentinel.worker.runtime import Worker, WorkerCancellation
from tests.conftest import Clock
from tests.integration.test_execution_orchestration import (
    NOW,
    ScriptedTransport,
    create_execution,
    response,
    telemetry,
)

pytest_plugins = ("tests.integration.test_execution_orchestration",)

pytestmark = pytest.mark.integration


class UnavailableExporter(SpanExporter):
    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        return SpanExportResult.FAILURE


def unavailable_telemetry() -> OpenTelemetryTraceLifecycle:
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(UnavailableExporter()))
    return OpenTelemetryTraceLifecycle(provider.get_tracer("sentinel.test.tempo-unavailable"))


async def test_worker_consumes_execute_execution_and_does_not_double_complete(
    engine: Engine, seeded_orchestration_catalog: None
) -> None:
    execution_id, jobs = create_execution(engine)
    orchestrator = ExecutionOrchestrator(
        PostgresOrchestrationStore(sessionmaker(engine, expire_on_commit=False), clock=lambda: NOW),
        ScriptedTransport(iter([response("ok", kind="text")])),
        EnvironmentSecretResolver({}),
        unavailable_telemetry(),
        clock=lambda: NOW,
    )
    worker = Worker(
        WorkService(jobs),
        uuid4(),
        handlers={"execute_execution": execution_handler(orchestrator)},
    )

    assert await worker.run_once()

    with Session(engine) as session:
        execution = session.get(ExecutionRow, execution_id)
        job = session.scalar(
            select(JobRow).where(
                JobRow.subject_id == execution_id,
                JobRow.kind == "execute_execution",
            )
        )
    assert execution is not None and execution.status == "completed"
    assert job is not None and job.state == "succeeded"
    with Session(engine) as session:
        attempts = list(session.scalars(select(TestAttemptRow)))
    assert len(attempts) == 1 and attempts[0].state == "evaluated"


async def test_heartbeat_loss_discards_in_memory_transport_result(
    engine: Engine,
    seeded_orchestration_catalog: None,
    clock: Clock,
) -> None:
    execution_id, jobs = create_execution(engine)
    jobs.clock = clock
    entered = Event()
    orchestration_finished = Event()

    class BlockingTransport:
        def dispatch(self, request: PreparedRequest) -> TransportResult:
            raise AssertionError("worker must use cancellable transport seam")

        def dispatch_cancellable(
            self, request: PreparedRequest, cancellation: CancellationSignal
        ) -> TransportResult:
            entered.set()
            cast(WorkerCancellation, cancellation).wait()
            return response("stale", kind="text")

    class FinishedOrchestrator(ExecutionOrchestrator):
        def run(
            self,
            lease: Lease,
            cancellation: CancellationSignal = NO_CANCELLATION,
        ) -> None:
            try:
                super().run(lease, cancellation)
            finally:
                orchestration_finished.set()

    async def expire_after_dispatch(_: float) -> None:
        await asyncio.to_thread(entered.wait)
        clock.advance(60)

    orchestrator = FinishedOrchestrator(
        PostgresOrchestrationStore(sessionmaker(engine, expire_on_commit=False), clock=clock),
        BlockingTransport(),
        EnvironmentSecretResolver({}),
        telemetry(),
        clock=clock,
    )
    worker = Worker(
        WorkService(jobs),
        uuid4(),
        handlers={"execute_execution": execution_handler(orchestrator)},
        delay=expire_after_dispatch,
    )

    assert await worker.run_once()
    assert orchestration_finished.is_set()

    with Session(engine) as session:
        execution = session.get(ExecutionRow, execution_id)
        job = session.scalar(select(JobRow).where(JobRow.subject_id == execution_id))
        attempts = list(session.scalars(select(TestAttemptRow)))
        artifacts = list(session.scalars(select(ResponseArtifactRow)))
    assert execution is not None and execution.status == "running"
    assert job is not None and job.state == "leased"
    assert len(attempts) == 1
    assert attempts[0].state == "dispatching"
    assert attempts[0].dispatch_certainty == "possibly_sent"
    assert artifacts == []

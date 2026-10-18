import asyncio
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from sentinel.execution.domain import InfrastructureFailure, Lease
from sentinel.execution.service import WorkService
from sentinel.persistence.models import ExecutionRow, JobRow
from sentinel.persistence.queue import PostgresJobStore
from sentinel.worker.runtime import HandlerCompletion, Worker, WorkerCancellation
from tests.conftest import Clock

pytestmark = pytest.mark.integration


async def test_worker_completes_durable_probe(store: PostgresJobStore, engine: Engine) -> None:
    service = WorkService(store)
    probe = service.enqueue_probe()
    worker = Worker(service, uuid4())
    assert await worker.run_once()
    with Session(engine) as session:
        job = session.get(JobRow, probe.job_id)
        execution = session.get(ExecutionRow, probe.execution_id)
        assert job is not None and execution is not None
        assert job.state == "succeeded"
        assert execution.status == "completed"
    assert not await worker.run_once()  # Polling discovers work without NOTIFY.


async def test_worker_heartbeat_during_handler(
    store: PostgresJobStore,
    engine: Engine,
    clock: Clock,
) -> None:
    service = WorkService(store)
    probe = service.enqueue_probe()
    heartbeat_due = asyncio.Event()
    beat_done = asyncio.Event()

    async def delay(_: float) -> None:
        await heartbeat_due.wait()
        heartbeat_due.clear()
        clock.advance(15)

    async def health() -> None:
        beat_done.set()

    async def handler(_: Lease, cancellation: WorkerCancellation) -> HandlerCompletion:
        heartbeat_due.set()
        await beat_done.wait()
        with Session(engine) as session:
            job = session.get(JobRow, probe.job_id)
            assert job is not None
            assert job.lease_expires_at == clock.value + timedelta(seconds=60)
        return HandlerCompletion.AUTOMATIC

    worker = Worker(service, uuid4(), handlers={"probe": handler}, delay=delay, health=health)
    # Default start is at 00:00:00; after heartbeat expiration must be 00:01:15.
    await worker.run_once()


async def test_lease_loss_cancels_handler_before_completion(
    store: PostgresJobStore,
    engine: Engine,
    clock: Clock,
) -> None:
    service = WorkService(store)
    probe = service.enqueue_probe()
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def delay(_: float) -> None:
        await started.wait()
        clock.advance(60)

    async def handler(_: Lease, cancellation: WorkerCancellation) -> HandlerCompletion:
        started.set()
        try:
            await asyncio.to_thread(cancellation.wait)
            cancellation.raise_if_cancelled()
        finally:
            cancelled.set()
        raise AssertionError("unreachable")

    worker = Worker(service, uuid4(), handlers={"probe": handler}, delay=delay)
    await worker.run_once()
    assert cancelled.is_set()
    with Session(engine) as session:
        job = session.get(JobRow, probe.job_id)
        assert job is not None
        assert job.state == "leased"  # Recovery waits for a fresh fenced claim.
    assert service.claim(uuid4()) is not None


@pytest.mark.parametrize(
    ("error", "state"),
    [(InfrastructureFailure(), "pending"), (RuntimeError("canary-secret"), "dead")],
)
async def test_worker_classifies_handler_failures_without_logging_raw_error(
    store: PostgresJobStore,
    engine: Engine,
    error: Exception,
    state: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    service = WorkService(store)
    probe = service.enqueue_probe()

    async def handler(_: Lease, cancellation: WorkerCancellation) -> HandlerCompletion:
        raise error

    await Worker(service, uuid4(), handlers={"probe": handler}).run_once()
    with Session(engine) as session:
        job = session.get(JobRow, probe.job_id)
        assert job is not None
        assert job.state == state
    assert "canary-secret" not in caplog.text


async def test_shutdown_cancels_handler_and_leaves_reclaimable_lease(
    store: PostgresJobStore,
    engine: Engine,
) -> None:
    service = WorkService(store)
    probe = service.enqueue_probe()
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def handler(_: Lease, cancellation: WorkerCancellation) -> HandlerCompletion:
        started.set()
        try:
            await asyncio.to_thread(cancellation.wait)
            cancellation.raise_if_cancelled()
        finally:
            cancelled.set()
        raise AssertionError("unreachable")

    task = asyncio.create_task(Worker(service, uuid4(), handlers={"probe": handler}).run_once())
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert cancelled.is_set()
    with Session(engine) as session:
        job = session.get(JobRow, probe.job_id)
        assert job is not None
        assert job.state == "leased"


async def test_missing_handler_is_terminal(store: PostgresJobStore, engine: Engine) -> None:
    service = WorkService(store)
    probe = service.enqueue_probe()
    await Worker(service, uuid4(), handlers={}).run_once()
    with Session(engine) as session:
        job = session.get(JobRow, probe.job_id)
        assert job is not None
        assert job.state == "dead"
        assert job.last_error_code == "handler_not_found"


@pytest.mark.parametrize("error", [InfrastructureFailure(), RuntimeError("canary-secret")])
async def test_heartbeat_failure_cancels_work_without_checkpointing(
    store: PostgresJobStore,
    engine: Engine,
    clock: Clock,
    error: Exception,
    caplog: pytest.LogCaptureFixture,
) -> None:
    class FailedHeartbeatStore(PostgresJobStore):
        def heartbeat(self, lease: Lease, lease_seconds: int) -> None:
            raise error

    failing = FailedHeartbeatStore(store.sessions, clock=clock)
    service = WorkService(failing)
    probe = service.enqueue_probe()
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def delay(_: float) -> None:
        await started.wait()

    async def handler(_: Lease, cancellation: WorkerCancellation) -> HandlerCompletion:
        started.set()
        try:
            await asyncio.to_thread(cancellation.wait)
            cancellation.raise_if_cancelled()
        finally:
            cancelled.set()
        raise AssertionError("unreachable")

    await Worker(service, uuid4(), handlers={"probe": handler}, delay=delay).run_once()
    assert cancelled.is_set()
    assert "canary-secret" not in caplog.text
    with Session(engine) as session:
        job = session.get(JobRow, probe.job_id)
        execution = session.get(ExecutionRow, probe.execution_id)
        assert job is not None and execution is not None
        assert job.state == "leased"
        assert execution.status == "running"
    clock.advance(60)
    recovered = store.claim(uuid4(), 60)
    assert recovered is not None
    assert recovered.delivery_count == 2

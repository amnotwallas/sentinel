from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from threading import Event as ThreadEvent
from typing import cast
from uuid import UUID

import pytest

from sentinel.execution.domain import InfrastructureFailure, Lease
from sentinel.execution.ports import DispatchCancelled
from sentinel.execution.service import WorkService
from sentinel.worker.runtime import HandlerCompletion, Worker, WorkerCancellation

LEASE = Lease(
    UUID("10000000-0000-4000-8000-000000000001"),
    UUID("10000000-0000-4000-8000-000000000002"),
    "execute_execution",
    UUID("10000000-0000-4000-8000-000000000003"),
    UUID("10000000-0000-4000-8000-000000000004"),
    datetime(2030, 1, 1, tzinfo=UTC),
    1,
)


class RecordingService:
    def __init__(self, *, heartbeat_error: Exception | None = None) -> None:
        self.heartbeat_error = heartbeat_error
        self.claimed = False
        self.started = 0
        self.completed = 0
        self.failed = 0

    def claim(self, owner: UUID) -> Lease | None:
        if self.claimed:
            return None
        self.claimed = True
        return LEASE

    def heartbeat(self, lease: Lease) -> None:
        if self.heartbeat_error is not None:
            raise self.heartbeat_error

    def start(self, lease: Lease) -> None:
        self.started += 1

    def complete(self, lease: Lease) -> None:
        self.completed += 1

    def fail(self, lease: Lease, code: object, *, retryable: bool) -> None:
        self.failed += 1


class BlockingService(RecordingService):
    def __init__(self, blocked_method: str, *, heartbeat_error: Exception | None = None) -> None:
        super().__init__(heartbeat_error=heartbeat_error)
        self.blocked_method = blocked_method
        self.entered = ThreadEvent()
        self.release = ThreadEvent()
        self.finished = ThreadEvent()
        self.calls: dict[str, int] = {}

    def _block(self, method: str) -> None:
        self.calls[method] = self.calls.get(method, 0) + 1
        if self.blocked_method != method:
            return
        self.entered.set()
        self.release.wait()
        self.finished.set()

    def claim(self, owner: UUID) -> Lease | None:
        self._block("claim")
        return super().claim(owner)

    def heartbeat(self, lease: Lease) -> None:
        self._block("heartbeat")
        super().heartbeat(lease)

    def start(self, lease: Lease) -> None:
        self._block("start")
        super().start(lease)

    def complete(self, lease: Lease) -> None:
        self._block("complete")
        super().complete(lease)

    def fail(self, lease: Lease, code: object, *, retryable: bool) -> None:
        self._block("fail")
        super().fail(lease, code, retryable=retryable)


async def test_durably_completed_handler_is_not_completed_twice() -> None:
    service = RecordingService()

    async def handler(lease: Lease, cancellation: WorkerCancellation) -> HandlerCompletion:
        assert not cancellation.is_cancelled()
        return HandlerCompletion.DURABLY_COMPLETED

    worker = Worker(
        cast(WorkService, service),
        LEASE.owner,
        handlers={LEASE.kind: handler},
    )

    assert await worker.run_once()
    assert service.started == 1
    assert service.completed == 0
    assert service.failed == 0


async def test_heartbeat_failure_signals_running_handler_before_returning() -> None:
    service = RecordingService(heartbeat_error=InfrastructureFailure())
    started = asyncio.Event()
    signal: WorkerCancellation | None = None

    async def delay(_: float) -> None:
        await started.wait()

    async def handler(lease: Lease, cancellation: WorkerCancellation) -> HandlerCompletion:
        nonlocal signal
        signal = cancellation
        started.set()
        await asyncio.to_thread(cancellation.wait)
        cancellation.raise_if_cancelled()
        raise AssertionError("unreachable")

    worker = Worker(
        cast(WorkService, service),
        LEASE.owner,
        handlers={LEASE.kind: handler},
        delay=delay,
    )

    assert await worker.run_once()
    assert signal is not None and signal.is_cancelled()
    assert service.completed == 0
    assert service.failed == 0


async def test_automatic_handler_completion_preserves_probe_behavior() -> None:
    service = RecordingService()

    async def handler(lease: Lease, cancellation: WorkerCancellation) -> HandlerCompletion:
        return HandlerCompletion.AUTOMATIC

    worker = Worker(
        cast(WorkService, service),
        LEASE.owner,
        handlers={LEASE.kind: handler},
    )

    assert await worker.run_once()
    assert service.completed == 1
    assert service.failed == 0


async def test_dispatch_cancelled_is_never_recorded_as_handler_failure() -> None:
    service = RecordingService()

    async def handler(lease: Lease, cancellation: WorkerCancellation) -> HandlerCompletion:
        raise DispatchCancelled

    worker = Worker(
        cast(WorkService, service),
        LEASE.owner,
        handlers={LEASE.kind: handler},
    )

    assert await worker.run_once()
    assert service.completed == 0
    assert service.failed == 0


async def test_heartbeat_failure_joins_cooperative_execution_thread() -> None:
    service = RecordingService(heartbeat_error=InfrastructureFailure())
    entered = ThreadEvent()
    cancellation_seen = ThreadEvent()
    release = ThreadEvent()
    finished = ThreadEvent()
    wrapper_cancelled = asyncio.Event()

    async def delay(_: float) -> None:
        await asyncio.to_thread(entered.wait)

    async def handler(lease: Lease, cancellation: WorkerCancellation) -> HandlerCompletion:
        def execute() -> None:
            entered.set()
            cancellation.wait()
            cancellation_seen.set()
            release.wait()
            try:
                cancellation.raise_if_cancelled()
            finally:
                finished.set()

        try:
            await asyncio.to_thread(execute)
        except asyncio.CancelledError:
            wrapper_cancelled.set()
            raise
        raise AssertionError("cancelled execution returned")

    worker = Worker(
        cast(WorkService, service),
        LEASE.owner,
        handlers={LEASE.kind: handler},
        delay=delay,
    )

    task = asyncio.create_task(worker.run_once())
    await asyncio.to_thread(cancellation_seen.wait)
    await asyncio.sleep(0)
    was_cancelled = wrapper_cancelled.is_set()
    returned_before_thread = task.done()
    release.set()
    assert await task
    assert not was_cancelled
    assert not returned_before_thread
    assert finished.is_set()
    assert service.completed == 0
    assert service.failed == 0


async def test_shutdown_joins_cooperative_execution_thread_before_propagating() -> None:
    service = RecordingService()
    entered = ThreadEvent()
    cancellation_seen = ThreadEvent()
    release = ThreadEvent()
    finished = ThreadEvent()
    wrapper_cancelled = asyncio.Event()

    async def handler(lease: Lease, cancellation: WorkerCancellation) -> HandlerCompletion:
        def execute() -> None:
            entered.set()
            cancellation.wait()
            cancellation_seen.set()
            release.wait()
            try:
                cancellation.raise_if_cancelled()
            finally:
                finished.set()

        try:
            await asyncio.to_thread(execute)
        except asyncio.CancelledError:
            wrapper_cancelled.set()
            raise
        raise AssertionError("cancelled execution returned")

    task = asyncio.create_task(
        Worker(
            cast(WorkService, service),
            LEASE.owner,
            handlers={LEASE.kind: handler},
        ).run_once()
    )
    await asyncio.to_thread(entered.wait)
    task.cancel()
    await asyncio.to_thread(cancellation_seen.wait)
    await asyncio.sleep(0)
    was_cancelled = wrapper_cancelled.is_set()
    returned_before_thread = task.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert not was_cancelled
    assert not returned_before_thread
    assert finished.is_set()
    assert service.completed == 0
    assert service.failed == 0


async def test_simultaneous_heartbeat_and_dispatch_cancellation_never_fails_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = RecordingService(heartbeat_error=InfrastructureFailure())
    release = asyncio.Event()

    async def delay(_: float) -> None:
        release.set()

    async def handler(lease: Lease, cancellation: WorkerCancellation) -> HandlerCompletion:
        await release.wait()
        raise DispatchCancelled

    original_wait = asyncio.wait

    async def settle_both(
        tasks: set[asyncio.Task[HandlerCompletion] | asyncio.Task[None]],
        *,
        return_when: object,
    ) -> tuple[set[asyncio.Task[object]], set[asyncio.Task[object]]]:
        await asyncio.gather(*tasks, return_exceptions=True)
        return cast(set[asyncio.Task[object]], tasks), set()

    monkeypatch.setattr(asyncio, "wait", settle_both)

    worker = Worker(
        cast(WorkService, service),
        LEASE.owner,
        handlers={LEASE.kind: handler},
        delay=delay,
    )

    assert await worker.run_once()
    assert service.completed == 0
    assert service.failed == 0
    monkeypatch.setattr(asyncio, "wait", original_wait)


async def test_shutdown_joins_blocking_claim_even_after_repeated_cancellation() -> None:
    service = BlockingService("claim")
    task = asyncio.create_task(Worker(cast(WorkService, service), LEASE.owner).run_once())
    await asyncio.to_thread(service.entered.wait)

    task.cancel()
    await asyncio.sleep(0)
    task.cancel()
    await asyncio.sleep(0)
    returned_before_thread = task.done()
    service.release.set()

    with pytest.raises(asyncio.CancelledError):
        await task
    assert not returned_before_thread
    assert service.finished.is_set()
    assert service.calls["claim"] == 1


async def test_handler_completion_joins_in_flight_heartbeat_before_checkpoint() -> None:
    service = BlockingService("heartbeat")
    delay_calls = 0

    async def delay(_: float) -> None:
        nonlocal delay_calls
        delay_calls += 1
        if delay_calls > 1:
            await asyncio.Event().wait()

    async def handler(lease: Lease, cancellation: WorkerCancellation) -> HandlerCompletion:
        await asyncio.to_thread(service.entered.wait)
        return HandlerCompletion.AUTOMATIC

    task = asyncio.create_task(
        Worker(
            cast(WorkService, service),
            LEASE.owner,
            handlers={LEASE.kind: handler},
            delay=delay,
        ).run_once()
    )
    await asyncio.to_thread(service.entered.wait)
    await asyncio.sleep(0)
    returned_before_thread = task.done()
    completed_before_thread = service.completed
    service.release.set()

    assert await task
    assert not returned_before_thread
    assert completed_before_thread == 0
    assert service.finished.is_set()
    assert service.calls["heartbeat"] == 1
    assert service.completed == 1


@pytest.mark.parametrize("blocked_method", ["start", "complete", "fail"])
async def test_shutdown_joins_worker_owned_database_checkpoint(blocked_method: str) -> None:
    service = BlockingService(blocked_method)

    async def success(lease: Lease, cancellation: WorkerCancellation) -> HandlerCompletion:
        return HandlerCompletion.AUTOMATIC

    async def failure(lease: Lease, cancellation: WorkerCancellation) -> HandlerCompletion:
        raise RuntimeError("synthetic")

    handler = failure if blocked_method == "fail" else success
    task = asyncio.create_task(
        Worker(
            cast(WorkService, service),
            LEASE.owner,
            handlers={LEASE.kind: handler},
        ).run_once()
    )
    await asyncio.to_thread(service.entered.wait)
    task.cancel()
    await asyncio.sleep(0)
    returned_before_thread = task.done()
    service.release.set()

    with pytest.raises(asyncio.CancelledError):
        await task
    assert not returned_before_thread
    assert service.finished.is_set()
    assert service.calls[blocked_method] == 1
    expected = {
        "start": (1, 0, 0),
        "complete": (1, 1, 0),
        "fail": (1, 0, 1),
    }
    assert (service.started, service.completed, service.failed) == expected[blocked_method]

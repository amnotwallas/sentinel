import asyncio
from collections.abc import Awaitable, Callable
from contextlib import suppress
from enum import StrEnum
from threading import Event
from uuid import UUID

from opentelemetry import trace
from opentelemetry.trace import Tracer

from sentinel.execution.domain import ErrorCode, InfrastructureFailure, Lease, LeaseLost
from sentinel.execution.ports import CancellationSignal, DispatchCancelled
from sentinel.execution.service import WorkService
from sentinel.telemetry.runtime import event


class HandlerCompletion(StrEnum):
    AUTOMATIC = "automatic"
    DURABLY_COMPLETED = "durably_completed"


class WorkerCancellation(CancellationSignal):
    """Thread-safe signal shared with synchronous execution and transport code."""

    def __init__(self) -> None:
        self._event = Event()

    def cancel(self) -> None:
        self._event.set()

    def is_cancelled(self) -> bool:
        return self._event.is_set()

    def raise_if_cancelled(self) -> None:
        if self.is_cancelled():
            raise DispatchCancelled

    def wait(self) -> None:
        self._event.wait()


Handler = Callable[[Lease, WorkerCancellation], Awaitable[HandlerCompletion]]
Delay = Callable[[float], Awaitable[None]]
Health = Callable[[], Awaitable[None]]


async def joined_to_thread[**P, R](
    function: Callable[P, R], /, *args: P.args, **kwargs: P.kwargs
) -> R:
    """Run one blocking call without abandoning its thread on task cancellation."""
    work = asyncio.create_task(asyncio.to_thread(function, *args, **kwargs))
    cancellation: asyncio.CancelledError | None = None
    while True:
        try:
            result = await asyncio.shield(work)
        except asyncio.CancelledError as error:
            cancellation = error
            if work.cancelled():
                raise
            continue
        except Exception:
            if cancellation is not None:
                raise cancellation from None
            raise
        if cancellation is not None:
            raise cancellation
        return result


async def probe_handler(_: Lease, cancellation: WorkerCancellation) -> HandlerCompletion:
    """No target I/O. The surrounding fenced checkpoints prove durable orchestration."""
    cancellation.raise_if_cancelled()
    return HandlerCompletion.AUTOMATIC


async def no_health() -> None:
    pass


class Worker:
    def __init__(
        self,
        service: WorkService,
        owner: UUID,
        *,
        heartbeat_seconds: float = 15,
        handlers: dict[str, Handler] | None = None,
        delay: Delay = asyncio.sleep,
        health: Health = no_health,
        tracer: Tracer | None = None,
    ) -> None:
        self.service = service
        self.owner = owner
        self.heartbeat_seconds = heartbeat_seconds
        self.handlers = handlers if handlers is not None else {"probe": probe_handler}
        self.delay = delay
        self.health = health
        self.tracer = tracer or trace.get_tracer(__name__)

    async def _heartbeat(self, lease: Lease, cancellation: WorkerCancellation) -> None:
        try:
            while True:
                await self.delay(self.heartbeat_seconds)
                await joined_to_thread(self.service.heartbeat, lease)
                await self.health()
                event("job_heartbeat", job_id=lease.job_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            cancellation.cancel()
            raise

    async def _handle(
        self, lease: Lease, handler: Handler, cancellation: WorkerCancellation
    ) -> HandlerCompletion:
        cancellation.raise_if_cancelled()
        await joined_to_thread(self.service.start, lease)
        cancellation.raise_if_cancelled()
        return await handler(lease, cancellation)

    @staticmethod
    async def _drain_work(work: asyncio.Task[HandlerCompletion]) -> None:
        while not work.done():
            try:
                await asyncio.shield(work)
            except asyncio.CancelledError:
                if work.cancelled():
                    break
            except Exception:
                break
        if work.done():
            with suppress(asyncio.CancelledError, Exception):
                work.result()

    async def run_once(self) -> bool:
        with self.tracer.start_as_current_span(
            "sentinel.job.claim",
            record_exception=False,
            set_status_on_exception=False,
        ) as claim_span:
            lease = await joined_to_thread(self.service.claim, self.owner)
            if lease is not None:
                claim_span.set_attribute("sentinel.job.kind", lease.kind)
                claim_span.set_attribute("sentinel.job.delivery", lease.delivery_count)
        if lease is None:
            return False
        event("job_claimed", job_id=lease.job_id)
        handler = self.handlers.get(lease.kind)
        if handler is None:
            await joined_to_thread(
                self.service.fail,
                lease,
                ErrorCode.HANDLER_NOT_FOUND,
                retryable=False,
            )
            return True
        cancellation = WorkerCancellation()
        heartbeat = asyncio.create_task(self._heartbeat(lease, cancellation))
        work = asyncio.create_task(self._handle(lease, handler, cancellation))
        failure: Exception | None = None
        completion: HandlerCompletion | None = None
        heartbeat_won = False
        try:
            with self.tracer.start_as_current_span(
                "sentinel.job.handle",
                record_exception=False,
                set_status_on_exception=False,
                attributes={
                    "sentinel.job.kind": lease.kind,
                    "sentinel.job.delivery": lease.delivery_count,
                },
            ):
                done, _ = await asyncio.wait({work, heartbeat}, return_when=asyncio.FIRST_COMPLETED)
                if work in done:
                    completion = await work
                    if heartbeat.done():
                        heartbeat_won = True
                        await heartbeat
                elif heartbeat in done:
                    heartbeat_won = True
                    await heartbeat  # Raises on expired ownership or database outage.
                    raise RuntimeError("heartbeat_stopped")
        except asyncio.CancelledError:
            cancellation.cancel()
            await self._drain_work(work)
            raise
        except DispatchCancelled:
            cancellation.cancel()
            await self._drain_work(work)
            event("job_lease_unconfirmed", job_id=lease.job_id)
            return True
        except Exception as exc:
            # Heartbeat failure means we cannot confirm ownership. Do not checkpoint or retry.
            if heartbeat_won:
                cancellation.cancel()
                await self._drain_work(work)
                event("job_lease_unconfirmed", job_id=lease.job_id)
                return True
            failure = exc
        finally:
            heartbeat.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await heartbeat
            if not work.done():
                cancellation.cancel()
                await self._drain_work(work)
        if cancellation.is_cancelled():
            event("job_lease_unconfirmed", job_id=lease.job_id)
            return True
        try:
            if failure is None:
                if completion == HandlerCompletion.AUTOMATIC:
                    cancellation.raise_if_cancelled()
                    await joined_to_thread(self.service.complete, lease)
                event("job_succeeded", job_id=lease.job_id)
            elif isinstance(failure, LeaseLost):
                event("job_lease_lost", job_id=lease.job_id)
            else:
                retryable = isinstance(failure, InfrastructureFailure)
                code = ErrorCode.INFRASTRUCTURE_FAILURE if retryable else ErrorCode.HANDLER_FAILED
                await joined_to_thread(self.service.fail, lease, code, retryable=retryable)
                event("job_retry_or_dead" if retryable else "job_dead", job_id=lease.job_id)
        except (LeaseLost, InfrastructureFailure):
            # The committed outcome may be unknown; re-delivery inspects durable state.
            event("job_checkpoint_unconfirmed", job_id=lease.job_id)
        return True

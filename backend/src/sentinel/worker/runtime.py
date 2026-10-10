import asyncio
from collections.abc import Awaitable, Callable
from contextlib import suppress
from uuid import UUID

from opentelemetry import trace
from opentelemetry.trace import Tracer

from sentinel.execution.domain import ErrorCode, InfrastructureFailure, Lease, LeaseLost
from sentinel.execution.service import WorkService
from sentinel.telemetry.runtime import event

Handler = Callable[[Lease], Awaitable[None]]
Delay = Callable[[float], Awaitable[None]]
Health = Callable[[], Awaitable[None]]


async def probe_handler(_: Lease) -> None:
    """No target I/O. The surrounding fenced checkpoints prove durable orchestration."""


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

    async def _heartbeat(self, lease: Lease) -> None:
        while True:
            await self.delay(self.heartbeat_seconds)
            await asyncio.to_thread(self.service.heartbeat, lease)
            await self.health()
            event("job_heartbeat", job_id=lease.job_id)

    async def _handle(self, lease: Lease, handler: Handler) -> None:
        await asyncio.to_thread(self.service.start, lease)
        await handler(lease)

    async def run_once(self) -> bool:
        lease = await asyncio.to_thread(self.service.claim, self.owner)
        if lease is None:
            return False
        event("job_claimed", job_id=lease.job_id)
        handler = self.handlers.get(lease.kind)
        if handler is None:
            await asyncio.to_thread(
                self.service.fail,
                lease,
                ErrorCode.HANDLER_NOT_FOUND,
                retryable=False,
            )
            return True
        heartbeat = asyncio.create_task(self._heartbeat(lease))
        work = asyncio.create_task(self._handle(lease, handler))
        failure: Exception | None = None
        try:
            with self.tracer.start_as_current_span(
                "worker.handle",
                record_exception=False,
                set_status_on_exception=False,
                attributes={
                    "sentinel.job.id": str(lease.job_id),
                    "sentinel.job.delivery": lease.delivery_count,
                },
            ):
                done, _ = await asyncio.wait({work, heartbeat}, return_when=asyncio.FIRST_COMPLETED)
                if heartbeat in done:
                    await heartbeat  # Raises on expired ownership or database outage.
                await work
        except Exception as exc:
            # Heartbeat failure means we cannot confirm ownership. Do not checkpoint or retry.
            if heartbeat.done():
                event("job_lease_unconfirmed", job_id=lease.job_id)
                return True
            failure = exc
        finally:
            for task in (heartbeat, work):
                task.cancel()
            for task in (heartbeat, work):
                with suppress(asyncio.CancelledError, Exception):
                    await task
        try:
            if failure is None:
                await asyncio.to_thread(self.service.complete, lease)
                event("job_succeeded", job_id=lease.job_id)
            elif isinstance(failure, LeaseLost):
                event("job_lease_lost", job_id=lease.job_id)
            else:
                retryable = isinstance(failure, InfrastructureFailure)
                code = ErrorCode.INFRASTRUCTURE_FAILURE if retryable else ErrorCode.HANDLER_FAILED
                await asyncio.to_thread(self.service.fail, lease, code, retryable=retryable)
                event("job_retry_or_dead" if retryable else "job_dead", job_id=lease.job_id)
        except (LeaseLost, InfrastructureFailure):
            # The committed outcome may be unknown; re-delivery inspects durable state.
            event("job_checkpoint_unconfirmed", job_id=lease.job_id)
        return True

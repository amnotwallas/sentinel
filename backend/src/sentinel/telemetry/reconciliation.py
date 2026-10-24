"""Fenced, delayed direct-trace reconciliation for durable correlation jobs."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

from sentinel.execution.domain import Lease
from sentinel.execution.ports import CancellationSignal
from sentinel.persistence.queue import PostgresJobStore
from sentinel.telemetry.ports import TraceLookupPort

LOOKUP_OFFSETS = (0, 1, 3, 7, 15, 31, 59)
_SCHEDULER_TICK_SECONDS = 1.0
Delay = Callable[[float], Awaitable[None]]


async def _joined_to_thread[**P, R](
    function: Callable[P, R], /, *args: P.args, **kwargs: P.kwargs
) -> R:
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


class TraceReconciliationService:
    """Runs one bounded lookup schedule without target or execution capabilities."""

    def __init__(
        self,
        store: PostgresJobStore,
        lookup: TraceLookupPort,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        delay: Delay = asyncio.sleep,
    ) -> None:
        self.store = store
        self.lookup = lookup
        self.clock = clock
        self.delay = delay

    async def _wait_until(self, due: datetime, cancellation: CancellationSignal) -> None:
        while True:
            cancellation.raise_if_cancelled()
            now = self.clock()
            if now.tzinfo is None:
                now = now.replace(tzinfo=UTC)
            if due.tzinfo is None:
                due = due.replace(tzinfo=UTC)
            remaining = (due - now).total_seconds()
            if remaining <= 0:
                return
            await self.delay(min(remaining, _SCHEDULER_TICK_SECONDS))

    async def reconcile(self, lease: Lease, cancellation: CancellationSignal) -> None:
        while True:
            cancellation.raise_if_cancelled()
            snapshot = await _joined_to_thread(self.store.correlation_snapshot, lease)
            if snapshot.status in {"available", "expired"}:
                return
            if snapshot.lookup_attempt_count >= len(LOOKUP_OFFSETS):
                await self._wait_until(snapshot.deadline_at, cancellation)
                await _joined_to_thread(self.store.finalize_correlation, lease)
                return

            now = self.clock()
            if now.tzinfo is None:
                now = now.replace(tzinfo=UTC)
            origin = snapshot.first_checked_at or now
            due = origin + timedelta(seconds=LOOKUP_OFFSETS[snapshot.lookup_attempt_count])
            if now >= snapshot.deadline_at or due >= snapshot.deadline_at:
                await self._wait_until(snapshot.deadline_at, cancellation)
                await _joined_to_thread(self.store.finalize_correlation, lease)
                return
            await self._wait_until(due, cancellation)
            cancellation.raise_if_cancelled()
            if self.clock() >= snapshot.deadline_at:
                await _joined_to_thread(self.store.finalize_correlation, lease)
                return
            lookup_result = await _joined_to_thread(
                self.lookup.lookup,
                snapshot.trace_id,
                expected_span_id=snapshot.expected_span_id,
                deadline=snapshot.deadline_at,
            )
            update = await _joined_to_thread(self.store.record_trace_lookup, lease, lookup_result)
            if update.terminal:
                return

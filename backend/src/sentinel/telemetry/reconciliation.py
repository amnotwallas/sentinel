"""Fenced, delayed direct-trace reconciliation for durable correlation jobs."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

from sentinel.execution.domain import Lease
from sentinel.execution.ports import CancellationSignal
from sentinel.persistence.queue import PostgresJobStore
from sentinel.telemetry.evidence import MAX_LINKED_MATCHES
from sentinel.telemetry.ports import LinkedTrace, TraceLookupPort

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
        linked_search_enabled: bool = False,
    ) -> None:
        self.store = store
        self.lookup = lookup
        self.clock = clock
        self.delay = delay
        self.linked_search_enabled = linked_search_enabled

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
            linked_traces: tuple[LinkedTrace, ...] = ()
            search_supported = False
            if self.linked_search_enabled:
                try:
                    search_supported = await _joined_to_thread(self.lookup.search_supported)
                except Exception:
                    search_supported = False
            if search_supported:
                try:
                    linked_traces = await _joined_to_thread(
                        self.lookup.search_attempt,
                        snapshot.attempt_id,
                        start_at=snapshot.dispatch_at,
                        end_at=snapshot.deadline_at,
                        limit=MAX_LINKED_MATCHES,
                    )
                except Exception:
                    linked_traces = ()
            update = await _joined_to_thread(
                self.store.record_trace_lookup, lease, lookup_result, linked_traces
            )
            if update.terminal:
                return

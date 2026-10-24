from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from sentinel.execution.domain import DispatchCertainty, Lease, LeaseLost, TransportOutcome
from sentinel.execution.ports import DispatchCancelled
from sentinel.persistence.attempts import PostgresAttemptStore
from sentinel.persistence.models import ExecutionRow, JobRow, TestAttemptRow, TraceReferenceRow
from sentinel.persistence.queue import PostgresJobStore
from sentinel.telemetry.ports import (
    ContextContinuity,
    TraceErrorCode,
    TraceLookup,
    TraceLookupStatus,
)
from sentinel.telemetry.reconciliation import LOOKUP_OFFSETS, TraceReconciliationService
from sentinel.worker.runtime import WorkerCancellation
from tests.conftest import Clock
from tests.integration.test_attempt_persistence import (
    NOW,
    _execution_with_job,
)

pytestmark = pytest.mark.integration
pytest_plugins = ("tests.integration.test_attempt_persistence",)


class ScriptedLookup:
    def __init__(self, results: Sequence[TraceLookup]) -> None:
        self.results = list(results)
        self.calls = 0

    def lookup(
        self,
        trace_id: str,
        *,
        expected_span_id: str,
        deadline: datetime,
    ) -> TraceLookup:
        self.calls += 1
        result = self.results[min(self.calls - 1, len(self.results) - 1)]
        assert result.trace_id == trace_id
        return result


def result(
    status: TraceLookupStatus,
    *,
    error: TraceErrorCode | None = None,
    span: str | None = None,
) -> TraceLookup:
    return TraceLookup(
        trace_id="b" * 32,
        client_span_id=span,
        status=status,
        error_code=error,
        trace_span_count=(
            2 if status in {TraceLookupStatus.AVAILABLE, TraceLookupStatus.PARTIAL} else 0
        ),
        error_span_count=1 if status is TraceLookupStatus.AVAILABLE else 0,
        services=(),
        context_continuity=(
            ContextContinuity.CONNECTED
            if status is TraceLookupStatus.AVAILABLE
            else ContextContinuity.BROKEN
            if status is TraceLookupStatus.PARTIAL
            else ContextContinuity.UNKNOWN
        ),
        response_size_bytes=128,
    )


def correlation_job(engine: Engine, clock: Clock) -> tuple[PostgresJobStore, Lease, Lease]:
    factory = sessionmaker(engine, expire_on_commit=False)
    item_id, _ = _execution_with_job(factory)
    queue = PostgresJobStore(factory, clock=clock)
    execution_lease = queue.claim(uuid4(), 1000)
    assert execution_lease is not None
    attempts = PostgresAttemptStore(factory, clock=clock)
    attempt = attempts.create_prepared(item_id, attempt_id=uuid4(), now=NOW)
    attempts.checkpoint_dispatch(
        attempt.id,
        execution_lease,
        fingerprint="a" * 64,
        trace_id="b" * 32,
        span_id="c" * 16,
    )
    attempts.record_transport_failure(
        attempt.id,
        execution_lease,
        outcome=TransportOutcome.TOTAL_TIMEOUT,
        certainty=DispatchCertainty.POSSIBLY_SENT,
    )
    correlation_lease = queue.claim(uuid4(), 60)
    assert correlation_lease is not None and correlation_lease.kind == "correlate_trace"
    return queue, correlation_lease, execution_lease


async def run_service(
    queue: PostgresJobStore,
    lease: Lease,
    lookup: ScriptedLookup,
    clock: Clock,
) -> None:
    async def delay(seconds: float) -> None:
        clock.advance(max(1, int(seconds)))
        queue.heartbeat(lease, 60)

    service = TraceReconciliationService(queue, lookup, clock=clock, delay=delay)
    await service.reconcile(lease, WorkerCancellation())


async def test_available_reconciliation_is_atomic_and_verdict_independent(
    engine: Engine, seeded_attempt_catalog: None, clock: Clock
) -> None:
    queue, lease, execution_lease = correlation_job(engine, clock)
    lookup = ScriptedLookup([result(TraceLookupStatus.AVAILABLE, span="c" * 16)])

    await run_service(queue, lease, lookup, clock)

    with Session(engine) as session:
        reference = session.scalar(
            select(TraceReferenceRow).where(TraceReferenceRow.id == lease.trace_reference_id)
        )
        job = session.get(JobRow, lease.job_id)
        execution = session.get(ExecutionRow, execution_lease.subject_id)
        attempt = session.scalar(
            select(TestAttemptRow).where(TestAttemptRow.primary_trace_id == "b" * 32)
        )
    assert reference is not None and reference.status == "available"
    assert reference.lookup_attempt_count == 1 and reference.evidence_json is not None
    assert set(reference.evidence_json) == {
        "schema_version",
        "primary_span_found",
        "trace_span_count",
        "error_span_count",
        "services",
        "deployments",
        "linked_match_count",
        "context_continuity",
        "comparison_anchor",
    }
    assert job is not None and job.state == "succeeded" and job.delivery_count == 1
    assert execution is not None and execution.status == "queued"
    assert attempt is not None and attempt.state == "transport_failed"
    assert lookup.calls == 1


async def test_delayed_arrival_uses_frozen_schedule_and_separate_counters(
    engine: Engine, seeded_attempt_catalog: None, clock: Clock
) -> None:
    queue, lease, _ = correlation_job(engine, clock)
    lookup = ScriptedLookup(
        [
            result(TraceLookupStatus.MISSING, error=TraceErrorCode.NOT_FOUND),
            result(TraceLookupStatus.AVAILABLE, span="c" * 16),
        ]
    )

    await run_service(queue, lease, lookup, clock)

    with Session(engine) as session:
        reference = session.get(TraceReferenceRow, lease.trace_reference_id)
        job = session.get(JobRow, lease.job_id)
    assert reference is not None and reference.status == "available"
    assert reference.lookup_attempt_count == 2
    assert job is not None and job.delivery_count == 1 and job.state == "succeeded"
    assert lookup.calls == 2


@pytest.mark.parametrize(
    ("status", "error", "expected"),
    [
        (TraceLookupStatus.MISSING, TraceErrorCode.NOT_FOUND, "expired"),
        (TraceLookupStatus.TEMPO_UNAVAILABLE, TraceErrorCode.TIMEOUT, "tempo_unavailable"),
        (TraceLookupStatus.PARTIAL, TraceErrorCode.INVALID_TRACE, "partial"),
    ],
)
async def test_deadline_terminal_states_are_truthful(
    engine: Engine,
    seeded_attempt_catalog: None,
    clock: Clock,
    status: TraceLookupStatus,
    error: TraceErrorCode,
    expected: str,
) -> None:
    queue, lease, _ = correlation_job(engine, clock)
    lookup = ScriptedLookup([result(status, error=error)])

    await run_service(queue, lease, lookup, clock)

    with Session(engine) as session:
        reference = session.get(TraceReferenceRow, lease.trace_reference_id)
        job = session.get(JobRow, lease.job_id)
    assert reference is not None and reference.status == expected
    assert reference.lookup_attempt_count == len(LOOKUP_OFFSETS)
    assert job is not None and job.state == "succeeded"
    assert lookup.calls == len(LOOKUP_OFFSETS)


async def test_partial_can_converge_before_deadline(
    engine: Engine, seeded_attempt_catalog: None, clock: Clock
) -> None:
    queue, lease, _ = correlation_job(engine, clock)
    lookup = ScriptedLookup(
        [
            result(TraceLookupStatus.PARTIAL, error=TraceErrorCode.INVALID_TRACE),
            result(TraceLookupStatus.AVAILABLE, span="c" * 16),
        ]
    )

    await run_service(queue, lease, lookup, clock)

    with Session(engine) as session:
        reference = session.get(TraceReferenceRow, lease.trace_reference_id)
    assert reference is not None and reference.status == "available"
    assert reference.lookup_attempt_count == 2


async def test_tempo_outage_can_recover_before_deadline(
    engine: Engine, seeded_attempt_catalog: None, clock: Clock
) -> None:
    queue, lease, _ = correlation_job(engine, clock)
    lookup = ScriptedLookup(
        [
            result(TraceLookupStatus.TEMPO_UNAVAILABLE, error=TraceErrorCode.TIMEOUT),
            result(TraceLookupStatus.AVAILABLE, span="c" * 16),
        ]
    )

    await run_service(queue, lease, lookup, clock)

    with Session(engine) as session:
        reference = session.get(TraceReferenceRow, lease.trace_reference_id)
    assert reference is not None and reference.status == "available"
    assert reference.lookup_attempt_count == 2


async def test_worker_interruption_leaves_delivery_recoverable(
    engine: Engine, seeded_attempt_catalog: None, clock: Clock
) -> None:
    queue, lease, _ = correlation_job(engine, clock)
    lookup = ScriptedLookup([result(TraceLookupStatus.MISSING, error=TraceErrorCode.NOT_FOUND)])
    cancellation = WorkerCancellation()

    async def interrupt_after_wait(seconds: float) -> None:
        clock.advance(max(1, int(seconds)))
        cancellation.cancel()

    service = TraceReconciliationService(queue, lookup, clock=clock, delay=interrupt_after_wait)
    with pytest.raises(DispatchCancelled):
        await service.reconcile(lease, cancellation)

    with Session(engine) as session:
        reference = session.get(TraceReferenceRow, lease.trace_reference_id)
        job = session.get(JobRow, lease.job_id)
    assert reference is not None and reference.status == "missing"
    assert job is not None and job.state == "leased" and job.delivery_count == 1

    clock.advance(60)
    recovered = queue.claim(uuid4(), 60)
    assert recovered is not None and recovered.delivery_count == 2


async def test_stale_fence_rejects_lookup_persistence(
    engine: Engine, seeded_attempt_catalog: None, clock: Clock
) -> None:
    queue, lease, _ = correlation_job(engine, clock)
    clock.advance(61)
    with pytest.raises(LeaseLost):
        queue.record_trace_lookup(
            lease,
            result(TraceLookupStatus.AVAILABLE, span="c" * 16),
        )
    with Session(engine) as session:
        reference = session.get(TraceReferenceRow, lease.trace_reference_id)
    assert reference is not None and reference.lookup_attempt_count == 0


async def test_reclaimed_delivery_resumes_without_duplicate_job_or_reference(
    engine: Engine, seeded_attempt_catalog: None, clock: Clock
) -> None:
    queue, lease, _ = correlation_job(engine, clock)
    first = result(TraceLookupStatus.MISSING, error=TraceErrorCode.NOT_FOUND)
    queue.record_trace_lookup(lease, first)
    clock.advance(61)
    recovered = queue.claim(uuid4(), 60)
    assert recovered is not None and recovered.delivery_count == 2
    assert recovered.trace_reference_id == lease.trace_reference_id
    with Session(engine) as session:
        assert (
            session.scalar(
                select(TraceReferenceRow.id).where(TraceReferenceRow.attempt_id.is_not(None))
            )
            is not None
        )
        assert (
            session.scalar(
                select(JobRow.id).where(JobRow.trace_reference_id == lease.trace_reference_id)
            )
            == lease.job_id
        )


async def test_delivery_exhaustion_without_lookup_is_safe_terminal_state(
    engine: Engine, seeded_attempt_catalog: None, clock: Clock
) -> None:
    queue, lease, _ = correlation_job(engine, clock)
    for _ in range(2):
        clock.advance(60)
        recovered = queue.claim(uuid4(), 60)
        assert recovered is not None
        lease = recovered
    clock.advance(60)
    assert queue.claim(uuid4(), 60) is None

    with Session(engine) as session:
        reference = session.get(TraceReferenceRow, lease.trace_reference_id)
        job = session.get(JobRow, lease.job_id)
    assert reference is not None
    assert reference.status == "tempo_unavailable"
    assert reference.last_error_code == "correlation_delivery_exhausted"
    assert reference.lookup_attempt_count == 0
    assert job is not None and job.state == "dead"

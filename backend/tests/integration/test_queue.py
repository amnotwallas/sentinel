from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from sentinel.execution.domain import ErrorCode, JobState, Lease, LeaseLost
from sentinel.persistence.models import ExecutionRow, JobRow
from sentinel.persistence.queue import PostgresJobStore
from tests.conftest import Clock

pytestmark = pytest.mark.integration


def test_creation_and_claim_survive_new_repository(store: PostgresJobStore, engine: Engine) -> None:
    probe = store.enqueue_probe(3)
    restarted = PostgresJobStore(sessionmaker(engine, expire_on_commit=False), clock=store.clock)
    # Stored work is visible through a completely separate adapter/connection.
    with Session(engine) as session:
        assert session.get(ExecutionRow, probe.execution_id) is not None
        assert session.get(JobRow, probe.job_id) is not None
    lease = restarted.claim(uuid4(), 60)
    assert lease is not None
    assert lease.job_id == probe.job_id
    assert lease.delivery_count == 1
    assert store.claim(uuid4(), 60) is None


def test_concurrent_workers_claim_distinct_jobs(store: PostgresJobStore) -> None:
    probes = [store.enqueue_probe(3) for _ in range(2)]
    barrier = Barrier(2)

    def claim() -> Lease | None:
        barrier.wait(timeout=5)
        return store.claim(uuid4(), 60)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(claim) for _ in range(2)]
        leases = [future.result(timeout=5) for future in futures]
    assert all(lease is not None for lease in leases)
    assert {lease.job_id for lease in leases if lease is not None} == {
        probe.job_id for probe in probes
    }


def test_claim_skips_row_locked_by_another_transaction(
    store: PostgresJobStore,
    engine: Engine,
) -> None:
    first = store.enqueue_probe(3)
    second = store.enqueue_probe(3)
    with Session(engine) as blocker, blocker.begin():
        blocker.execute(select(JobRow).where(JobRow.id == first.job_id).with_for_update())
        lease = store.claim(uuid4(), 60)
        assert lease is not None
        assert lease.job_id == second.job_id


def test_expiration_reclaim_fences_old_owner(store: PostgresJobStore, clock: Clock) -> None:
    store.enqueue_probe(3)
    first = store.claim(uuid4(), 60)
    assert first is not None
    clock.advance(60)
    with pytest.raises(LeaseLost):
        store.heartbeat(first, 60)
    with pytest.raises(LeaseLost):
        store.complete(first)
    second = store.claim(uuid4(), 60)
    assert second is not None
    assert second.job_id == first.job_id
    assert second.token != first.token
    assert second.delivery_count == 2
    for operation in (store.start, store.complete):
        with pytest.raises(LeaseLost):
            operation(first)
    with pytest.raises(LeaseLost):
        store.fail(first, ErrorCode.INFRASTRUCTURE_FAILURE, retryable=True)


def test_heartbeat_extends_lease(store: PostgresJobStore, clock: Clock, engine: Engine) -> None:
    store.enqueue_probe(3)
    lease = store.claim(uuid4(), 60)
    assert lease is not None
    clock.advance(15)
    store.heartbeat(lease, 60)
    clock.advance(45)
    assert store.claim(uuid4(), 60) is None
    with Session(engine) as session:
        row = session.get(JobRow, lease.job_id)
        assert row is not None
        assert row.lease_expires_at == lease.expires_at + timedelta(seconds=15)
    clock.advance(15)
    assert store.claim(uuid4(), 60) is not None


def test_retry_delays_and_third_failure_are_terminal(
    store: PostgresJobStore,
    clock: Clock,
    engine: Engine,
) -> None:
    probe = store.enqueue_probe(3)
    for delay in (5, 30):
        lease = store.claim(uuid4(), 60)
        assert lease is not None
        store.start(lease)
        store.fail(lease, ErrorCode.INFRASTRUCTURE_FAILURE, retryable=True)
        assert store.claim(uuid4(), 60) is None
        clock.advance(delay)
    lease = store.claim(uuid4(), 60)
    assert lease is not None
    assert lease.delivery_count == 3
    store.fail(lease, ErrorCode.INFRASTRUCTURE_FAILURE, retryable=True)
    assert store.claim(uuid4(), 60) is None
    with Session(engine) as session:
        job = session.get(JobRow, probe.job_id)
        execution = session.get(ExecutionRow, probe.execution_id)
        assert job is not None and execution is not None
        assert job.state == JobState.DEAD
        assert job.lease_token is None
        assert job.finished_at == clock.value
        assert execution.status == "failed"
        assert execution.verdict == "not_evaluated"


def test_abandoned_final_delivery_becomes_dead(
    store: PostgresJobStore,
    clock: Clock,
    engine: Engine,
) -> None:
    probe = store.enqueue_probe(1)
    assert store.claim(uuid4(), 60) is not None
    clock.advance(60)
    assert store.claim(uuid4(), 60) is None
    with Session(engine) as session:
        job = session.get(JobRow, probe.job_id)
        execution = session.get(ExecutionRow, probe.execution_id)
        assert job is not None and execution is not None
        assert job.state == "dead"
        assert job.last_error_code == "delivery_exhausted"
        assert execution.status == "failed"


def test_success_is_terminal_and_updates_subject_atomically(
    store: PostgresJobStore,
    engine: Engine,
) -> None:
    probe = store.enqueue_probe(3)
    lease = store.claim(uuid4(), 60)
    assert lease is not None
    store.start(lease)
    store.complete(lease)
    assert store.claim(uuid4(), 60) is None
    with pytest.raises(LeaseLost):
        store.complete(lease)
    with Session(engine) as session:
        execution = session.get(ExecutionRow, probe.execution_id)
        job = session.get(JobRow, probe.job_id)
        assert execution is not None and job is not None
        assert execution.status == "completed"
        assert job.state == "succeeded"


def test_nonretryable_failure_does_not_wait_for_exhaustion(
    store: PostgresJobStore,
    engine: Engine,
) -> None:
    probe = store.enqueue_probe(3)
    lease = store.claim(uuid4(), 60)
    assert lease is not None
    store.fail(lease, ErrorCode.HANDLER_NOT_FOUND, retryable=False)
    with Session(engine) as session:
        job = session.get(JobRow, probe.job_id)
        assert job is not None
        assert job.state == "dead"
        assert job.delivery_count == 1


def test_transaction_failure_rolls_back_subject_and_job(
    store: PostgresJobStore,
    engine: Engine,
) -> None:
    ids = iter([uuid4(), uuid4()])
    store.ids = lambda: next(ids)
    first = store.enqueue_probe(3)
    # Force a job PK collision after inserting a new subject in the transaction.
    ids = iter([uuid4(), first.job_id])
    with pytest.raises(IntegrityError):
        store.enqueue_probe(3)
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(JobRow)) == 1
        assert session.scalar(select(func.count()).select_from(ExecutionRow)) == 1


def test_database_rejects_invalid_lease_shape(engine: Engine, store: PostgresJobStore) -> None:
    probe = store.enqueue_probe(3)
    with pytest.raises(IntegrityError), Session(engine) as session, session.begin():
        row = session.get(JobRow, probe.job_id)
        assert row is not None
        row.state = "leased"  # Missing owner/token/expiration violates DB invariant.


def test_concurrent_claims_for_one_job_have_one_winner(store: PostgresJobStore) -> None:
    store.enqueue_probe(3)
    barrier = Barrier(2)

    def claim() -> Lease | None:
        barrier.wait(timeout=5)
        return store.claim(uuid4(), 60)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(claim) for _ in range(2)]
        results = [future.result(timeout=5) for future in futures]
    assert sum(result is not None for result in results) == 1


def test_completion_write_failure_rolls_back_both_rows(
    store: PostgresJobStore,
    engine: Engine,
) -> None:
    probe = store.enqueue_probe(3)
    lease = store.claim(uuid4(), 60)
    assert lease is not None
    store.start(lease)
    # Force a real DB write error during the combined checkpoint transaction.
    with engine.begin() as connection:
        connection.execute(
            text(
                "ALTER TABLE executions ADD CONSTRAINT test_reject_completion "
                "CHECK (status <> 'completed')"
            )
        )
    try:
        with pytest.raises(IntegrityError):
            store.complete(lease)
        with Session(engine) as session:
            job = session.get(JobRow, probe.job_id)
            execution = session.get(ExecutionRow, probe.execution_id)
            assert job is not None and execution is not None
            assert job.state == "leased"
            assert execution.status == "running"
    finally:
        with engine.begin() as connection:
            connection.execute(
                text("ALTER TABLE executions DROP CONSTRAINT test_reject_completion")
            )


def test_completion_requires_running_execution(store: PostgresJobStore) -> None:
    store.enqueue_probe(3)
    lease = store.claim(uuid4(), 60)
    assert lease is not None
    with pytest.raises(ValueError, match="running execution"):
        store.complete(lease)

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from sentinel.execution.attempts import ResponseArtifact
from sentinel.execution.domain import (
    DispatchCertainty,
    LeaseLost,
    TransportOutcome,
)
from sentinel.persistence.attempts import AttemptConflict, PostgresAttemptStore
from sentinel.persistence.models import (
    EnvironmentRevisionRow,
    EnvironmentRow,
    ExecutionItemRow,
    ExecutionRow,
    JobRow,
    ProjectRow,
    TestAttemptRow,
    TestCaseRevisionRow,
    TestCaseRow,
)
from sentinel.persistence.queue import PostgresJobStore

pytestmark = pytest.mark.integration
NOW = datetime(2030, 1, 1, tzinfo=UTC)
PROJECT_ID = UUID("10000000-0000-4000-8000-000000001001")
ENVIRONMENT_ID = UUID("10000000-0000-4000-8000-000000001002")
ENVIRONMENT_REVISION_ID = UUID("10000000-0000-4000-8000-000000001003")
TEST_CASE_ID = UUID("10000000-0000-4000-8000-000000001004")
TEST_CASE_REVISION_ID = UUID("10000000-0000-4000-8000-000000001005")


@pytest.fixture
def seeded_attempt_catalog(engine: Engine) -> None:
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory.begin() as session:
        session.add(
            ProjectRow(id=PROJECT_ID, name="attempt-project", state_version=1, created_at=NOW)
        )
        session.flush()
        session.add(
            EnvironmentRow(
                id=ENVIRONMENT_ID,
                project_id=PROJECT_ID,
                name="attempt-env",
                active_revision_id=ENVIRONMENT_REVISION_ID,
                state_version=1,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.add(
            TestCaseRow(
                id=TEST_CASE_ID,
                project_id=PROJECT_ID,
                name="attempt-case",
                active_revision_id=TEST_CASE_REVISION_ID,
                state_version=1,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.flush()
        session.add(
            EnvironmentRevisionRow(
                id=ENVIRONMENT_REVISION_ID,
                environment_id=ENVIRONMENT_ID,
                version=1,
                definition={},
                created_at=NOW,
            )
        )
        session.add(
            TestCaseRevisionRow(
                id=TEST_CASE_REVISION_ID,
                test_case_id=TEST_CASE_ID,
                version=1,
                definition={},
                policy_fingerprint="a" * 64,
                created_at=NOW,
            )
        )


def _execution_with_job(factory: sessionmaker[Session]) -> tuple[UUID, UUID]:
    execution_id, item_id, job_id = uuid4(), uuid4(), uuid4()
    with factory.begin() as session:
        session.add(
            ExecutionRow(
                id=execution_id,
                project_id=PROJECT_ID,
                environment_id=ENVIRONMENT_ID,
                environment_revision_id=ENVIRONMENT_REVISION_ID,
                source_type="test_case",
                source_id=TEST_CASE_ID,
                source_revision_id=TEST_CASE_REVISION_ID,
                status="queued",
                created_at=NOW,
            )
        )
        session.flush()
        session.add(
            ExecutionItemRow(
                id=item_id,
                execution_id=execution_id,
                ordinal=0,
                project_id=PROJECT_ID,
                test_case_id=TEST_CASE_ID,
                test_case_revision_id=TEST_CASE_REVISION_ID,
                test_case_revision_version=1,
                status="pending",
            )
        )
        session.add(
            JobRow(
                id=job_id,
                kind="execute_execution",
                subject_id=execution_id,
                state="pending",
                available_at=NOW,
                delivery_count=0,
                max_deliveries=3,
                created_at=NOW,
            )
        )
    return item_id, job_id


def test_attempt_checkpoint_and_redacted_response_are_fenced(
    engine: Engine, seeded_attempt_catalog: None
) -> None:
    factory = sessionmaker(engine, expire_on_commit=False)
    item_id, _ = _execution_with_job(factory)
    lease = PostgresJobStore(factory, clock=lambda: NOW).claim(uuid4(), 60)
    assert lease is not None
    store = PostgresAttemptStore(factory, clock=lambda: NOW)
    attempt = store.create_prepared(item_id, attempt_id=uuid4(), now=NOW)
    assert attempt.dispatch_certainty == DispatchCertainty.NOT_STARTED
    attempt = store.checkpoint_dispatch(
        attempt.id, lease, fingerprint="a" * 64, trace_id="b" * 32, span_id="c" * 16
    )
    assert attempt.dispatch_certainty == DispatchCertainty.POSSIBLY_SENT
    completed = store.record_response(
        attempt.id,
        lease,
        ResponseArtifact(
            attempt.id,
            200,
            {"authorization": "[REDACTED]"},
            "json",
            {"value": "[REDACTED]"},
            24,
            False,
            False,
            NOW,
            NOW + timedelta(days=7),
        ),
    )
    assert completed.state.value == "response_received"
    with Session(engine) as session:
        row = session.scalar(select(TestAttemptRow).where(TestAttemptRow.id == attempt.id))
        assert row is not None and row.request_fingerprint == "a" * 64


def test_expired_lease_cannot_commit_attempt_outcome(
    engine: Engine, seeded_attempt_catalog: None
) -> None:
    factory = sessionmaker(engine, expire_on_commit=False)
    item_id, _ = _execution_with_job(factory)
    lease = PostgresJobStore(factory, clock=lambda: NOW).claim(uuid4(), 60)
    assert lease is not None
    store = PostgresAttemptStore(factory, clock=lambda: NOW + timedelta(seconds=61))
    attempt = store.create_prepared(item_id, attempt_id=uuid4(), now=NOW)
    with pytest.raises(LeaseLost):
        store.checkpoint_dispatch(
            attempt.id, lease, fingerprint="a" * 64, trace_id="b" * 32, span_id="c" * 16
        )
    with Session(engine) as session:
        row = session.get(TestAttemptRow, attempt.id)
        assert row is not None and row.state == "prepared"


def test_not_sent_requires_positive_phase_proof(
    engine: Engine, seeded_attempt_catalog: None
) -> None:
    factory = sessionmaker(engine, expire_on_commit=False)
    item_id, _ = _execution_with_job(factory)
    lease = PostgresJobStore(factory, clock=lambda: NOW).claim(uuid4(), 60)
    assert lease is not None
    store = PostgresAttemptStore(factory, clock=lambda: NOW)
    attempt = store.create_prepared(item_id, attempt_id=uuid4(), now=NOW)
    store.checkpoint_dispatch(
        attempt.id,
        lease,
        fingerprint="a" * 64,
        trace_id="b" * 32,
        span_id="c" * 16,
    )
    with pytest.raises(AttemptConflict):
        store.record_transport_failure(
            attempt.id,
            lease,
            outcome=TransportOutcome.DNS_FAILURE,
            certainty=DispatchCertainty.NOT_SENT,
        )
    failed = store.record_transport_failure(
        attempt.id,
        lease,
        outcome=TransportOutcome.DNS_FAILURE,
        certainty=DispatchCertainty.NOT_SENT,
        not_sent_proof="dns_failure",
    )
    assert failed.dispatch_certainty == DispatchCertainty.NOT_SENT


def test_replay_successor_can_dispatch_after_predecessor_link(
    engine: Engine, seeded_attempt_catalog: None
) -> None:
    factory = sessionmaker(engine, expire_on_commit=False)
    item_id, _ = _execution_with_job(factory)
    lease = PostgresJobStore(factory, clock=lambda: NOW).claim(uuid4(), 60)
    assert lease is not None
    store = PostgresAttemptStore(factory, clock=lambda: NOW)
    predecessor = store.create_prepared(item_id, attempt_id=uuid4(), now=NOW)
    successor = store.create_prepared(item_id, attempt_id=uuid4(), now=NOW)

    with factory.begin() as session:
        row = session.get(TestAttemptRow, predecessor.id)
        assert row is not None
        row.replay_successor_id = successor.id

    dispatched = store.checkpoint_dispatch(
        successor.id,
        lease,
        fingerprint="a" * 64,
        trace_id="b" * 32,
        span_id="c" * 16,
    )
    assert dispatched.state.value == "dispatching"
    assert dispatched.replay_successor_id is None

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic.command import downgrade, upgrade
from alembic.config import Config
from sqlalchemy import func, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DatabaseError, IntegrityError
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
    TraceReferenceRow,
)
from sentinel.persistence.queue import PostgresJobStore
from sentinel.persistence.trace_references import TraceReferenceRepository

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
        outcome=TransportOutcome.RESPONSE_RECEIVED,
    )
    assert completed.state.value == "response_received"
    with Session(engine) as session:
        row = session.scalar(select(TestAttemptRow).where(TestAttemptRow.id == attempt.id))
        assert row is not None and row.request_fingerprint == "a" * 64


def test_bounded_final_capture_preserves_response_limit_outcome(
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

    completed = store.record_response(
        attempt.id,
        lease,
        ResponseArtifact(
            attempt.id,
            200,
            {},
            "text",
            "bounded",
            7,
            True,
            False,
            NOW,
            NOW + timedelta(days=7),
        ),
        outcome=TransportOutcome.RESPONSE_LIMIT_EXCEEDED,
    )

    assert completed.state.value == "response_received"
    assert completed.dispatch_certainty == DispatchCertainty.RESPONSE_RECEIVED
    assert completed.transport_outcome == TransportOutcome.RESPONSE_LIMIT_EXCEEDED


@pytest.mark.parametrize(
    ("outcome", "stored_truncated", "invalid_truncated"),
    [
        (TransportOutcome.RESPONSE_RECEIVED, False, True),
        (TransportOutcome.RESPONSE_LIMIT_EXCEEDED, True, False),
    ],
)
def test_database_rejects_response_outcome_artifact_mismatch(
    engine: Engine,
    seeded_attempt_catalog: None,
    outcome: TransportOutcome,
    stored_truncated: bool,
    invalid_truncated: bool,
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
    store.record_response(
        attempt.id,
        lease,
        ResponseArtifact(
            attempt.id,
            200,
            {},
            "text",
            "bounded",
            7,
            stored_truncated,
            False,
            NOW,
            NOW + timedelta(days=7),
        ),
        outcome=outcome,
    )

    with pytest.raises(DatabaseError):
        with engine.begin() as connection:
            connection.execute(
                text("UPDATE response_artifacts SET truncated = :truncated WHERE attempt_id = :id"),
                {"id": attempt.id, "truncated": invalid_truncated},
            )


@pytest.mark.parametrize(
    ("stored_outcome", "truncated", "invalid_outcome"),
    [
        (
            TransportOutcome.RESPONSE_RECEIVED,
            False,
            TransportOutcome.RESPONSE_LIMIT_EXCEEDED,
        ),
        (
            TransportOutcome.RESPONSE_LIMIT_EXCEEDED,
            True,
            TransportOutcome.RESPONSE_RECEIVED,
        ),
    ],
)
def test_database_rejects_attempt_outcome_artifact_mismatch(
    engine: Engine,
    seeded_attempt_catalog: None,
    stored_outcome: TransportOutcome,
    truncated: bool,
    invalid_outcome: TransportOutcome,
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
    store.record_response(
        attempt.id,
        lease,
        ResponseArtifact(
            attempt.id,
            200,
            {},
            "text",
            "bounded",
            7,
            truncated,
            False,
            NOW,
            NOW + timedelta(days=7),
        ),
        outcome=stored_outcome,
    )

    with pytest.raises(DatabaseError):
        with engine.begin() as connection:
            connection.execute(
                text("UPDATE test_attempts SET transport_outcome = :outcome WHERE id = :id"),
                {"id": attempt.id, "outcome": invalid_outcome},
            )


def test_response_outcome_migration_downgrade_preserves_compatible_evidence(
    engine: Engine,
    seeded_attempt_catalog: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = engine.url.render_as_string(hide_password=False)
    monkeypatch.setenv("SENTINEL_DATABASE_URL", database_url)
    config = Config(str(Path(__file__).parents[2] / "alembic.ini"))
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
    store.record_response(
        attempt.id,
        lease,
        ResponseArtifact(
            attempt.id,
            200,
            {},
            "text",
            "bounded",
            7,
            True,
            False,
            NOW,
            NOW + timedelta(days=7),
        ),
        outcome=TransportOutcome.RESPONSE_LIMIT_EXCEEDED,
    )

    try:
        downgrade(config, "0008")
        with engine.connect() as connection:
            assert (
                connection.scalar(
                    text("SELECT transport_outcome FROM test_attempts WHERE id = :id"),
                    {"id": attempt.id},
                )
                == TransportOutcome.RESPONSE_RECEIVED
            )
            assert connection.execute(
                text(
                    "SELECT count(*), bool_and(truncated) FROM response_artifacts "
                    "WHERE attempt_id = :id"
                ),
                {"id": attempt.id},
            ).one() == (1, True)
        upgrade(config, "head")
        with engine.connect() as connection:
            assert (
                connection.scalar(
                    text("SELECT transport_outcome FROM test_attempts WHERE id = :id"),
                    {"id": attempt.id},
                )
                == TransportOutcome.RESPONSE_LIMIT_EXCEEDED
            )
            assert connection.execute(
                text(
                    "SELECT count(*), bool_and(truncated) FROM response_artifacts "
                    "WHERE attempt_id = :id"
                ),
                {"id": attempt.id},
            ).one() == (1, True)
    finally:
        upgrade(config, "head")


def test_migration_grandfathers_legacy_limit_failure_but_rejects_new_writes(
    engine: Engine,
    seeded_attempt_catalog: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = engine.url.render_as_string(hide_password=False)
    monkeypatch.setenv("SENTINEL_DATABASE_URL", database_url)
    config = Config(str(Path(__file__).parents[2] / "alembic.ini"))
    factory = sessionmaker(engine, expire_on_commit=False)
    item_id, _ = _execution_with_job(factory)
    lease = PostgresJobStore(factory, clock=lambda: NOW).claim(uuid4(), 60)
    assert lease is not None
    store = PostgresAttemptStore(factory, clock=lambda: NOW)
    legacy = store.create_prepared(item_id, attempt_id=uuid4(), now=NOW)
    candidate = store.create_prepared(item_id, attempt_id=uuid4(), now=NOW)
    for attempt in (legacy, candidate):
        store.checkpoint_dispatch(
            attempt.id,
            lease,
            fingerprint="a" * 64,
            trace_id=("b" if attempt.id == legacy.id else "d") * 32,
            span_id=("c" if attempt.id == legacy.id else "e") * 16,
        )

    try:
        downgrade(config, "0008")
        with engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE test_attempts SET state = 'transport_failed', "
                    "transport_outcome = 'response_limit_exceeded', finished_at = :now, "
                    "duration_ms = 0 WHERE id = :id"
                ),
                {"id": legacy.id, "now": NOW},
            )
        upgrade(config, "head")

        with engine.connect() as connection:
            assert connection.execute(
                text(
                    "SELECT state, dispatch_certainty, transport_outcome "
                    "FROM test_attempts WHERE id = :id"
                ),
                {"id": legacy.id},
            ).one() == (
                "transport_failed",
                "possibly_sent",
                "response_limit_exceeded",
            )
        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE test_attempts SET state = 'transport_failed', "
                        "transport_outcome = 'response_limit_exceeded', finished_at = :now, "
                        "duration_ms = 0 WHERE id = :id"
                    ),
                    {"id": candidate.id, "now": NOW},
                )
    finally:
        upgrade(config, "head")


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


def test_m5_primary_reference_and_correlation_job_are_atomic_and_idempotent(
    engine: Engine, seeded_attempt_catalog: None
) -> None:
    factory = sessionmaker(engine, expire_on_commit=False)
    item_id, _ = _execution_with_job(factory)
    queue = PostgresJobStore(factory, clock=lambda: NOW)
    lease = queue.claim(uuid4(), 60)
    assert lease is not None
    attempts = PostgresAttemptStore(factory, clock=lambda: NOW)
    attempt = attempts.create_prepared(item_id, attempt_id=uuid4(), now=NOW)
    attempts.checkpoint_dispatch(
        attempt.id, lease, fingerprint="a" * 64, trace_id="b" * 32, span_id="c" * 16
    )
    attempts.record_response(
        attempt.id,
        lease,
        ResponseArtifact(
            attempt.id,
            200,
            {},
            "text",
            "ok",
            2,
            False,
            False,
            NOW,
            NOW + timedelta(days=1),
        ),
        outcome=TransportOutcome.RESPONSE_RECEIVED,
    )
    with Session(engine) as session:
        reference = session.scalar(
            select(TraceReferenceRow).where(TraceReferenceRow.attempt_id == attempt.id)
        )
        assert reference is not None and reference.relation == "primary"
        assert (
            session.scalar(
                select(func.count(JobRow.id)).where(JobRow.trace_reference_id == reference.id)
            )
            == 1
        )

        execution = session.get(ExecutionRow, lease.subject_id)
        assert execution is not None and execution.status == "queued"

    # Reconciliation queue completion is fenced but never an execution transition.
    correlation = queue.claim(uuid4(), 60)
    assert correlation is not None and correlation.trace_reference_id == reference.id
    queue.start(correlation)
    queue.complete(correlation)
    with Session(engine) as session:
        execution = session.get(ExecutionRow, lease.subject_id)
        assert execution is not None and execution.status == "queued"

    # Repeating the terminal checkpoint is idempotent.
    with factory.begin() as session:
        reference = session.scalar(
            select(TraceReferenceRow).where(TraceReferenceRow.attempt_id == attempt.id)
        )
        assert reference is not None
        primary_id = reference.id
        persisted_attempt = session.get(TestAttemptRow, attempt.id)
        assert persisted_attempt is not None
        TraceReferenceRepository.finalize_primary(
            session,
            attempt=persisted_attempt,
            terminal_at=NOW,
            execution_id=lease.subject_id,
        )
    with Session(engine) as session:
        assert (
            session.scalar(
                select(func.count(JobRow.id)).where(JobRow.trace_reference_id == primary_id)
            )
            == 1
        )

    # A rolled-back terminal checkpoint leaves no durable correlation job.
    second = attempts.create_prepared(item_id, attempt_id=uuid4(), now=NOW)
    attempts.checkpoint_dispatch(
        second.id, lease, fingerprint="d" * 64, trace_id="e" * 32, span_id="f" * 16
    )
    with pytest.raises(RuntimeError):
        with factory.begin() as session:
            reference = session.scalar(
                select(TraceReferenceRow)
                .where(TraceReferenceRow.attempt_id == second.id)
                .with_for_update()
            )
            assert reference is not None
            second_id = reference.id
            persisted_attempt = session.get(TestAttemptRow, second.id)
            assert persisted_attempt is not None
            TraceReferenceRepository.finalize_primary(
                session,
                attempt=persisted_attempt,
                terminal_at=NOW,
                execution_id=lease.subject_id,
            )
            raise RuntimeError("rollback probe")
    with Session(engine) as session:
        assert (
            session.scalar(
                select(func.count(JobRow.id)).where(JobRow.trace_reference_id == second_id)
            )
            == 0
        )


def test_m5_scoped_reference_and_evidence_constraints_reject_cross_project_and_raw_data(
    engine: Engine, seeded_attempt_catalog: None
) -> None:
    factory = sessionmaker(engine, expire_on_commit=False)
    item_id, _ = _execution_with_job(factory)
    queue = PostgresJobStore(factory, clock=lambda: NOW)
    lease = queue.claim(uuid4(), 60)
    assert lease is not None
    attempts = PostgresAttemptStore(factory, clock=lambda: NOW)
    attempt = attempts.create_prepared(item_id, attempt_id=uuid4(), now=NOW)
    attempts.checkpoint_dispatch(
        attempt.id, lease, fingerprint="a" * 64, trace_id="b" * 32, span_id="c" * 16
    )
    with Session(engine) as session:
        item = session.get(ExecutionItemRow, item_id)
        assert item is not None
        with pytest.raises(IntegrityError):
            with session.begin_nested():
                session.add(
                    TraceReferenceRow(
                        id=uuid4(),
                        attempt_id=attempt.id,
                        execution_item_id=item.id,
                        execution_id=lease.subject_id,
                        project_id=uuid4(),
                        relation="linked",
                        trace_id="d" * 32,
                        correlation_source="baggage_attribute_search",
                        status="pending",
                        deadline_at=NOW,
                        lookup_attempt_count=0,
                        evidence_schema_version=1,
                        created_at=NOW,
                        updated_at=NOW,
                    )
                )
                session.flush()
        with pytest.raises(IntegrityError):
            with session.begin_nested():
                session.add(
                    TraceReferenceRow(
                        id=uuid4(),
                        attempt_id=attempt.id,
                        execution_item_id=item.id,
                        execution_id=lease.subject_id,
                        project_id=item.project_id,
                        relation="linked",
                        trace_id="d" * 32,
                        correlation_source="baggage_attribute_search",
                        status="pending",
                        deadline_at=NOW,
                        lookup_attempt_count=0,
                        evidence_schema_version=1,
                        evidence_json={"schema_version": 1, "services": "x" * 70000},
                        created_at=NOW,
                        updated_at=NOW,
                    )
                )
                session.flush()


def test_m5_migration_round_trip_preserves_legacy_attempt_without_backfill(
    engine: Engine,
    seeded_attempt_catalog: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = engine.url.render_as_string(hide_password=False)
    monkeypatch.setenv("SENTINEL_DATABASE_URL", database_url)
    config = Config(str(Path(__file__).parents[2] / "alembic.ini"))
    factory = sessionmaker(engine, expire_on_commit=False)
    item_id, _ = _execution_with_job(factory)
    legacy = PostgresAttemptStore(factory, clock=lambda: NOW).create_prepared(
        item_id, attempt_id=uuid4(), now=NOW
    )
    try:
        downgrade(config, "0010")
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT to_regclass('trace_references')")) is None
        upgrade(config, "head")
        with Session(engine) as session:
            assert session.get(TestAttemptRow, legacy.id) is not None
            assert (
                session.scalar(
                    select(func.count(TraceReferenceRow.id)).where(
                        TraceReferenceRow.attempt_id == legacy.id
                    )
                )
                == 0
            )
    finally:
        upgrade(config, "head")


def test_m5_correlation_recovery_fences_stale_delivery_without_replay(
    engine: Engine, seeded_attempt_catalog: None
) -> None:
    factory = sessionmaker(engine, expire_on_commit=False)
    item_id, _ = _execution_with_job(factory)
    clock = [NOW]
    queue = PostgresJobStore(factory, clock=lambda: clock[0])
    lease = queue.claim(uuid4(), 60)
    assert lease is not None
    attempts = PostgresAttemptStore(factory, clock=lambda: NOW)
    attempt = attempts.create_prepared(item_id, attempt_id=uuid4(), now=NOW)
    attempts.checkpoint_dispatch(
        attempt.id, lease, fingerprint="a" * 64, trace_id="b" * 32, span_id="c" * 16
    )
    attempts.record_transport_failure(
        attempt.id,
        lease,
        outcome=TransportOutcome.TOTAL_TIMEOUT,
        certainty=DispatchCertainty.POSSIBLY_SENT,
    )
    correlation = queue.claim(uuid4(), 60)
    assert correlation is not None
    clock[0] = NOW + timedelta(seconds=61)
    with pytest.raises(LeaseLost):
        queue.complete(correlation)
    recovered = queue.claim(uuid4(), 60)
    assert recovered is not None and recovered.delivery_count == 2
    with Session(engine) as session:
        execution = session.get(ExecutionRow, lease.subject_id)
        assert execution is not None and execution.status == "queued"


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


def test_bounded_final_capture_cannot_be_recorded_as_transport_failure(
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
            outcome=TransportOutcome.RESPONSE_LIMIT_EXCEEDED,
            certainty=DispatchCertainty.POSSIBLY_SENT,
        )


@pytest.mark.parametrize(
    ("outcome", "truncated"),
    [
        (TransportOutcome.DNS_FAILURE, False),
        (TransportOutcome.RESPONSE_RECEIVED, True),
        (TransportOutcome.RESPONSE_LIMIT_EXCEEDED, False),
    ],
)
def test_response_outcome_must_describe_the_bounded_capture(
    engine: Engine,
    seeded_attempt_catalog: None,
    outcome: TransportOutcome,
    truncated: bool,
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
        store.record_response(
            attempt.id,
            lease,
            ResponseArtifact(
                attempt.id,
                200,
                {},
                "text",
                "bounded",
                7,
                truncated,
                False,
                NOW,
                NOW + timedelta(days=7),
            ),
            outcome=outcome,
        )


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

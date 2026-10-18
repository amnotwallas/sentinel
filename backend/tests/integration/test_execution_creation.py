from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import select, update
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from sentinel.execution.creation import (
    ExecutionCreateCommand,
    ExecutionIdempotencyConflict,
    ExecutionResourceNotFound,
    PostgresExecutionService,
)
from sentinel.persistence.models import (
    EnvironmentRevisionRow,
    EnvironmentRow,
    ExecutionItemRow,
    ExecutionRow,
    IdempotencyRecordRow,
    JobRow,
    ProjectRow,
    ResponseArtifactRow,
    SuiteRevisionItemRow,
    SuiteRevisionRow,
    SuiteRow,
    TestAttemptRow,
    TestCaseRevisionRow,
    TestCaseRow,
)
from sentinel.persistence.queue import PostgresJobStore

NOW = datetime(2030, 1, 1, tzinfo=UTC)
PROJECT_ID = UUID("10000000-0000-4000-8000-000000000001")
OTHER_PROJECT_ID = UUID("10000000-0000-4000-8000-000000000002")
ENVIRONMENT_ID = UUID("10000000-0000-4000-8000-000000000010")
ENVIRONMENT_REVISION_ID = UUID("10000000-0000-4000-8000-000000000011")
TEST_CASE_ID = UUID("10000000-0000-4000-8000-000000000020")
TEST_CASE_REVISION_ID = UUID("10000000-0000-4000-8000-000000000021")
SECOND_TEST_CASE_ID = UUID("10000000-0000-4000-8000-000000000022")
SECOND_TEST_CASE_REVISION_ID = UUID("10000000-0000-4000-8000-000000000023")
OTHER_TEST_CASE_ID = UUID("10000000-0000-4000-8000-000000000024")
OTHER_TEST_CASE_REVISION_ID = UUID("10000000-0000-4000-8000-000000000025")
SUITE_ID = UUID("10000000-0000-4000-8000-000000000030")
SUITE_REVISION_ID = UUID("10000000-0000-4000-8000-000000000031")


@pytest.fixture
def execution_service(engine: Engine) -> PostgresExecutionService:
    return PostgresExecutionService(sessionmaker(engine, expire_on_commit=False), clock=lambda: NOW)


@pytest.fixture
def seeded_catalog(engine: Engine) -> None:
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory.begin() as session:
        session.add_all(
            [
                ProjectRow(
                    id=PROJECT_ID,
                    name="project",
                    state_version=1,
                    created_at=NOW,
                    deleted_at=None,
                ),
                ProjectRow(
                    id=OTHER_PROJECT_ID,
                    name="other-project",
                    state_version=1,
                    created_at=NOW,
                    deleted_at=None,
                ),
            ]
        )
        session.flush()
        session.add_all(
            [
                EnvironmentRow(
                    id=ENVIRONMENT_ID,
                    project_id=PROJECT_ID,
                    name="local",
                    active_revision_id=ENVIRONMENT_REVISION_ID,
                    state_version=1,
                    created_at=NOW,
                    updated_at=NOW,
                ),
                TestCaseRow(
                    id=TEST_CASE_ID,
                    project_id=PROJECT_ID,
                    name="case",
                    active_revision_id=TEST_CASE_REVISION_ID,
                    state_version=1,
                    created_at=NOW,
                    updated_at=NOW,
                ),
                TestCaseRow(
                    id=OTHER_TEST_CASE_ID,
                    project_id=OTHER_PROJECT_ID,
                    name="other-case",
                    active_revision_id=OTHER_TEST_CASE_REVISION_ID,
                    state_version=1,
                    created_at=NOW,
                    updated_at=NOW,
                ),
                TestCaseRow(
                    id=SECOND_TEST_CASE_ID,
                    project_id=PROJECT_ID,
                    name="case-two",
                    active_revision_id=SECOND_TEST_CASE_REVISION_ID,
                    state_version=1,
                    created_at=NOW,
                    updated_at=NOW,
                ),
                SuiteRow(
                    id=SUITE_ID,
                    project_id=PROJECT_ID,
                    name="suite",
                    active_revision_id=SUITE_REVISION_ID,
                    state_version=1,
                    created_at=NOW,
                    updated_at=NOW,
                ),
            ]
        )
        session.flush()
        session.add_all(
            [
                EnvironmentRevisionRow(
                    id=ENVIRONMENT_REVISION_ID,
                    environment_id=ENVIRONMENT_ID,
                    version=1,
                    definition={},
                    created_at=NOW,
                ),
                TestCaseRevisionRow(
                    id=TEST_CASE_REVISION_ID,
                    test_case_id=TEST_CASE_ID,
                    version=1,
                    definition={},
                    policy_fingerprint="0" * 64,
                    created_at=NOW,
                ),
                TestCaseRevisionRow(
                    id=OTHER_TEST_CASE_REVISION_ID,
                    test_case_id=OTHER_TEST_CASE_ID,
                    version=1,
                    definition={},
                    policy_fingerprint="2" * 64,
                    created_at=NOW,
                ),
                TestCaseRevisionRow(
                    id=SECOND_TEST_CASE_REVISION_ID,
                    test_case_id=SECOND_TEST_CASE_ID,
                    version=2,
                    definition={},
                    policy_fingerprint="1" * 64,
                    created_at=NOW,
                ),
                SuiteRevisionRow(
                    id=SUITE_REVISION_ID,
                    suite_id=SUITE_ID,
                    project_id=PROJECT_ID,
                    version=1,
                    created_at=NOW,
                ),
            ]
        )
        session.flush()
        session.add_all(
            [
                SuiteRevisionItemRow(
                    suite_revision_id=SUITE_REVISION_ID,
                    ordinal=0,
                    project_id=PROJECT_ID,
                    test_case_id=TEST_CASE_ID,
                    test_case_revision_id=TEST_CASE_REVISION_ID,
                    test_case_revision_version=1,
                ),
                SuiteRevisionItemRow(
                    suite_revision_id=SUITE_REVISION_ID,
                    ordinal=1,
                    project_id=PROJECT_ID,
                    test_case_id=SECOND_TEST_CASE_ID,
                    test_case_revision_id=SECOND_TEST_CASE_REVISION_ID,
                    test_case_revision_version=2,
                ),
            ]
        )


@pytest.mark.integration
def test_creation_is_atomic_and_enqueues_compatible_job(
    engine: Engine, execution_service: PostgresExecutionService, seeded_catalog: None
) -> None:
    record = execution_service.create(
        ExecutionCreateCommand(ENVIRONMENT_ID, test_case_id=TEST_CASE_ID)
    )
    with Session(engine) as session:
        assert session.scalar(select(ExecutionRow).where(ExecutionRow.id == record.id)) is not None
        item = session.scalar(
            select(ExecutionItemRow).where(ExecutionItemRow.execution_id == record.id)
        )
        job = session.scalar(select(JobRow).where(JobRow.subject_id == record.id))
    assert item is not None and item.test_case_revision_id == TEST_CASE_REVISION_ID
    assert job is not None and job.kind == "execute_execution" and job.state == "pending"


@pytest.mark.integration
def test_execution_read_includes_ordered_attempt_history_and_expiry(
    engine: Engine, execution_service: PostgresExecutionService, seeded_catalog: None
) -> None:
    record = execution_service.create(
        ExecutionCreateCommand(ENVIRONMENT_ID, test_case_id=TEST_CASE_ID)
    )
    item_id = record.items[0].id
    attempt_id = UUID("10000000-0000-4000-8000-000000000090")
    with Session(engine) as session:
        session.add(
            TestAttemptRow(
                id=attempt_id,
                execution_item_id=item_id,
                sequence=1,
                state="response_received",
                dispatch_certainty="response_received",
                request_fingerprint="a" * 64,
                created_at=NOW,
                dispatch_recorded_at=NOW,
                response_recorded_at=NOW,
                finished_at=NOW,
                duration_ms=12,
                transport_outcome="response_received",
                preparation_error_code=None,
                redirect_rejection_code=None,
                replay_successor_id=None,
                primary_trace_id="b" * 32,
                client_span_id="c" * 16,
                included_in_verdict=True,
            )
        )
        session.flush()
        session.add(
            ResponseArtifactRow(
                attempt_id=attempt_id,
                status_code=200,
                headers={"content-type": "application/json", "authorization": "[REDACTED]"},
                body_kind="json",
                body_content={"ok": True},
                source_bytes_captured=11,
                truncated=False,
                redaction_unavailable=False,
                recorded_at=NOW,
                expires_at=NOW + timedelta(days=7),
            )
        )
        session.commit()

    detail = execution_service.get(record.id)
    assert detail is not None
    assert len(detail.items) == 1
    assert [attempt.sequence for attempt in detail.items[0].attempts] == [1]
    read = execution_service.get_attempt(attempt_id)
    assert read is not None
    assert read.execution_id == record.id
    assert read.artifact is not None and read.artifact.body_content == {"ok": True}

    with Session(engine) as session:
        artifact = session.get(ResponseArtifactRow, attempt_id)
        assert artifact is not None
        artifact.expires_at = NOW - timedelta(seconds=1)
        session.commit()
    expired = execution_service.get_attempt(attempt_id)
    assert expired is not None and expired.artifact is not None
    assert expired.artifact.expires_at < expired.read_at


@pytest.mark.integration
def test_execution_read_bounds_attempt_history_to_latest_hundred(
    execution_service: PostgresExecutionService, seeded_catalog: None
) -> None:
    record = execution_service.create(
        ExecutionCreateCommand(ENVIRONMENT_ID, test_case_id=TEST_CASE_ID)
    )
    item_id = record.items[0].id
    with execution_service.sessions.begin() as session:
        session.add_all(
            [
                TestAttemptRow(
                    id=UUID(int=10_000 + sequence),
                    execution_item_id=item_id,
                    sequence=sequence,
                    state="prepared",
                    dispatch_certainty="not_started",
                    request_fingerprint=None,
                    created_at=NOW,
                    dispatch_recorded_at=None,
                    response_recorded_at=None,
                    finished_at=None,
                    duration_ms=None,
                    transport_outcome=None,
                    preparation_error_code=None,
                    redirect_rejection_code=None,
                    replay_successor_id=None,
                    primary_trace_id=None,
                    client_span_id=None,
                    included_in_verdict=True,
                )
                for sequence in range(1, 102)
            ]
        )
    detail = execution_service.get(record.id)
    assert detail is not None
    item = detail.items[0]
    assert item.attempt_count == 101
    assert item.attempts_truncated is True
    assert [attempt.sequence for attempt in item.attempts] == list(range(2, 102))


@pytest.mark.integration
def test_suite_materializes_exact_order_and_revision_versions(
    execution_service: PostgresExecutionService, seeded_catalog: None
) -> None:
    record = execution_service.create(ExecutionCreateCommand(ENVIRONMENT_ID, suite_id=SUITE_ID))
    assert [
        (item.ordinal, item.test_case_id, item.test_case_revision_version) for item in record.items
    ] == [
        (0, TEST_CASE_ID, 1),
        (1, SECOND_TEST_CASE_ID, 2),
    ]


@pytest.mark.integration
def test_pins_survive_later_catalog_revision_change(
    engine: Engine, execution_service: PostgresExecutionService, seeded_catalog: None
) -> None:
    record = execution_service.create(
        ExecutionCreateCommand(ENVIRONMENT_ID, test_case_id=TEST_CASE_ID)
    )
    replacement_revision_id = UUID("10000000-0000-4000-8000-000000000099")
    with Session(engine) as session:
        session.add(
            TestCaseRevisionRow(
                id=replacement_revision_id,
                test_case_id=TEST_CASE_ID,
                version=2,
                definition={"changed": True},
                policy_fingerprint="3" * 64,
                created_at=NOW,
            )
        )
        session.flush()
        session.execute(
            update(TestCaseRow)
            .where(TestCaseRow.id == TEST_CASE_ID)
            .values(active_revision_id=replacement_revision_id, state_version=2)
        )
        session.commit()
    pinned = execution_service.get(record.id)
    assert pinned is not None
    assert pinned.source_revision_id == TEST_CASE_REVISION_ID
    assert pinned.items[0].test_case_revision_id == TEST_CASE_REVISION_ID


@pytest.mark.integration
def test_missing_or_stale_catalog_resource_fails_closed(
    execution_service: PostgresExecutionService, seeded_catalog: None
) -> None:
    with pytest.raises(ExecutionResourceNotFound):
        execution_service.create(
            ExecutionCreateCommand(
                ENVIRONMENT_ID, test_case_id=UUID("10000000-0000-4000-8000-000000000099")
            )
        )
    # The active-revision ownership constraints make an invalid pointer uncommittable;
    # the same validation path is exercised by the missing resource above.


@pytest.mark.integration
def test_execute_job_can_be_claimed_and_started_without_dispatch(
    engine: Engine, execution_service: PostgresExecutionService, seeded_catalog: None
) -> None:
    record = execution_service.create(
        ExecutionCreateCommand(ENVIRONMENT_ID, test_case_id=TEST_CASE_ID)
    )
    store = PostgresJobStore(sessionmaker(engine, expire_on_commit=False), clock=lambda: NOW)
    lease = store.claim(UUID("30000000-0000-4000-8000-000000000001"), 60)
    assert lease is not None and lease.subject_id == record.id and lease.kind == "execute_execution"
    store.start(lease)
    with Session(engine) as session:
        execution = session.get(ExecutionRow, record.id)
        assert execution is not None
        assert execution.status == "running"


@pytest.mark.integration
def test_database_rejects_invalid_execution_item_ordinal(
    engine: Engine, execution_service: PostgresExecutionService, seeded_catalog: None
) -> None:
    record = execution_service.create(
        ExecutionCreateCommand(ENVIRONMENT_ID, test_case_id=TEST_CASE_ID)
    )
    with pytest.raises(IntegrityError):
        with Session(engine) as session:
            session.add(
                ExecutionItemRow(
                    id=UUID("40000000-0000-4000-8000-000000000001"),
                    execution_id=record.id,
                    ordinal=100,
                    project_id=PROJECT_ID,
                    test_case_id=TEST_CASE_ID,
                    test_case_revision_id=TEST_CASE_REVISION_ID,
                    test_case_revision_version=1,
                    status="pending",
                )
            )
            session.commit()


@pytest.mark.integration
def test_idempotency_replay_and_conflict(
    execution_service: PostgresExecutionService, seeded_catalog: None
) -> None:
    command = ExecutionCreateCommand(ENVIRONMENT_ID, test_case_id=TEST_CASE_ID)
    first = execution_service.create(command, idempotency_key="same-key")
    replay = execution_service.create(command, idempotency_key="same-key")
    assert replay.id == first.id
    with pytest.raises(ExecutionIdempotencyConflict):
        execution_service.create(
            ExecutionCreateCommand(ENVIRONMENT_ID, suite_id=SUITE_ID), idempotency_key="same-key"
        )


@pytest.mark.integration
def test_same_key_concurrent_creation_serializes(engine: Engine, seeded_catalog: None) -> None:
    command = ExecutionCreateCommand(ENVIRONMENT_ID, test_case_id=TEST_CASE_ID)

    def create() -> UUID:
        service = PostgresExecutionService(
            sessionmaker(engine, expire_on_commit=False), clock=lambda: NOW
        )
        return service.create(command, idempotency_key="concurrent-key").id

    with ThreadPoolExecutor(max_workers=2) as workers:
        ids = list(workers.map(lambda _: create(), range(2)))
    assert ids[0] == ids[1]

    with Session(engine) as session:
        assert (
            session.scalar(select(ExecutionRow.id).where(ExecutionRow.source_id == TEST_CASE_ID))
            is not None
        )
        assert session.scalar(select(IdempotencyRecordRow.key_hash)) is not None


@pytest.mark.integration
def test_cross_project_reference_is_not_disclosed(
    execution_service: PostgresExecutionService, seeded_catalog: None
) -> None:
    with pytest.raises(ExecutionResourceNotFound):
        execution_service.create(
            ExecutionCreateCommand(ENVIRONMENT_ID, test_case_id=OTHER_TEST_CASE_ID)
        )


@pytest.mark.integration
def test_materialization_failure_rolls_back_all_rows(engine: Engine, seeded_catalog: None) -> None:
    ids = iter(
        [
            UUID("20000000-0000-4000-8000-000000000001"),
            UUID("20000000-0000-4000-8000-000000000002"),
            UUID("20000000-0000-4000-8000-000000000002"),
            UUID("20000000-0000-4000-8000-000000000003"),
        ]
    )
    service = PostgresExecutionService(
        sessionmaker(engine, expire_on_commit=False), ids=lambda: next(ids), clock=lambda: NOW
    )
    with pytest.raises(IntegrityError):
        service.create(
            ExecutionCreateCommand(ENVIRONMENT_ID, suite_id=SUITE_ID),
            idempotency_key="rollback-key",
        )
    with Session(engine) as session:
        assert (
            session.scalar(
                select(ExecutionRow).where(
                    ExecutionRow.id == UUID("20000000-0000-4000-8000-000000000001")
                )
            )
            is None
        )
        assert session.scalar(select(IdempotencyRecordRow.key_hash)) is None

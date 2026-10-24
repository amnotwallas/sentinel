from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic.command import downgrade, upgrade
from alembic.config import Config
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from sqlalchemy import select, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DatabaseError, IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from sentinel.execution.creation import ExecutionCreateCommand, PostgresExecutionService
from sentinel.persistence.models import (
    BaselineActivationRow,
    BaselineComparisonRow,
    BaselineRow,
    EnvironmentRevisionRow,
    EnvironmentRow,
    EvaluationRow,
    ExecutionItemRow,
    ExecutionRow,
    ProjectRow,
    ResponseArtifactRow,
    TestAttemptRow,
    TestCaseRevisionRow,
    TestCaseRow,
    TraceReferenceRow,
)
from sentinel.persistence.regression import (
    BaselineComparisonInput,
    BoundedEvidence,
    EvaluationInput,
    PersistenceValidationError,
    PostgresEvaluationPersistence,
    bounded_evidence,
    validate_selected_values,
)

pytestmark = pytest.mark.integration
NOW = datetime(2030, 1, 1, tzinfo=UTC)


def _ids(seed: int) -> dict[str, UUID]:
    return {
        name: UUID(f"{seed:08d}-0000-4000-8000-{suffix}")
        for name, suffix in {
            "project": "000000000001",
            "environment": "000000000002",
            "environment_revision": "000000000003",
            "test_case": "000000000004",
            "test_case_revision": "000000000005",
            "execution": "000000000006",
            "item": "000000000007",
            "attempt": "000000000008",
            "baseline": "000000000009",
            "activation": "00000000000a",
        }.items()
    }


def _seed_scope(
    factory: sessionmaker[Session], *, seed: int = 71000000, with_baseline: bool = False
) -> dict[str, UUID]:
    ids = _ids(seed)
    with factory.begin() as session:
        session.add(
            ProjectRow(id=ids["project"], name=f"m4-{seed}", state_version=1, created_at=NOW)
        )
        session.flush()
        session.add(
            EnvironmentRow(
                id=ids["environment"],
                project_id=ids["project"],
                name="m4-env",
                active_revision_id=ids["environment_revision"],
                state_version=1,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.add(
            TestCaseRow(
                id=ids["test_case"],
                project_id=ids["project"],
                name="m4-case",
                active_revision_id=ids["test_case_revision"],
                state_version=1,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.flush()
        session.add(
            EnvironmentRevisionRow(
                id=ids["environment_revision"],
                environment_id=ids["environment"],
                version=1,
                definition={},
                created_at=NOW,
            )
        )
        session.add(
            TestCaseRevisionRow(
                id=ids["test_case_revision"],
                test_case_id=ids["test_case"],
                version=1,
                definition={},
                policy_fingerprint="a" * 64,
                created_at=NOW,
            )
        )
        session.flush()
        if with_baseline:
            session.add(
                BaselineRow(
                    id=ids["baseline"],
                    test_case_id=ids["test_case"],
                    environment_id=ids["environment"],
                    project_id=ids["project"],
                    version=1,
                    source_attempt_id=uuid4(),
                    source_execution_id=uuid4(),
                    source_test_case_revision_id=ids["test_case_revision"],
                    source_attempt_verdict="baseline_required",
                    source_finished_at=NOW,
                    policy_fingerprint="b" * 64,
                    selected_values_schema_version=1,
                    selected_values={"schema_version": 1, "values": []},
                    created_at=NOW,
                )
            )
            session.flush()
            session.add(
                BaselineActivationRow(
                    id=ids["activation"],
                    test_case_id=ids["test_case"],
                    environment_id=ids["environment"],
                    project_id=ids["project"],
                    baseline_id=ids["baseline"],
                    activated_at=NOW,
                )
            )
        session.flush()
        session.add(
            ExecutionRow(
                id=ids["execution"],
                project_id=ids["project"],
                environment_id=ids["environment"],
                environment_revision_id=ids["environment_revision"],
                source_type="test_case",
                source_id=ids["test_case"],
                source_revision_id=ids["test_case_revision"],
                status="running",
                result_contract_version=1,
                created_at=NOW,
            )
        )
        session.flush()
        session.add(
            ExecutionItemRow(
                id=ids["item"],
                execution_id=ids["execution"],
                ordinal=0,
                project_id=ids["project"],
                test_case_id=ids["test_case"],
                test_case_revision_id=ids["test_case_revision"],
                test_case_revision_version=1,
                result_contract_version=1,
                baseline_activation_id=ids["activation"] if with_baseline else None,
                baseline_id=ids["baseline"] if with_baseline else None,
                status="running",
            )
        )
        session.add(
            TestAttemptRow(
                id=ids["attempt"],
                execution_item_id=ids["item"],
                sequence=1,
                result_contract_version=1,
                state="response_received",
                dispatch_certainty="response_received",
                request_fingerprint="c" * 64,
                created_at=NOW,
                dispatch_recorded_at=NOW,
                response_recorded_at=NOW,
                transport_outcome="response_received",
                primary_trace_id="d" * 32,
                client_span_id="e" * 16,
                included_in_verdict=True,
            )
        )
        session.flush()
        session.add(
            ResponseArtifactRow(
                attempt_id=ids["attempt"],
                status_code=200,
                headers={"content-type": "application/json"},
                body_kind="json",
                body_content={"ok": True},
                source_bytes_captured=11,
                recorded_at=NOW,
                expires_at=NOW,
            )
        )
    return ids


def _evaluated_result(
    factory: sessionmaker[Session], ids: dict[str, UUID], *, with_evaluation: bool = True
) -> None:
    with factory.begin() as session:
        attempt = session.get(TestAttemptRow, ids["attempt"])
        assert attempt is not None
        attempt.state = "evaluated"
        attempt.verdict = "passed"
        PostgresEvaluationPersistence.add_result(
            session,
            attempt_id=attempt.id,
            comparison=BaselineComparisonInput(
                state="not_requested",
                baseline_activation_id=None,
                baseline_id=None,
                baseline_version=None,
                policy_fingerprint=None,
                checked_at=NOW,
            ),
            evaluations=(
                EvaluationInput(
                    id=uuid4(),
                    ordinal=0,
                    kind="assertion",
                    rule_id=uuid4(),
                    severity="required",
                    outcome="passed",
                    message_code="assertion_passed",
                    expected=BoundedEvidence("ok", False),
                    actual=BoundedEvidence("ok", False),
                    created_at=NOW,
                ),
            )
            if with_evaluation
            else (),
        )


def test_m4_rows_are_ordered_and_result_cardinality_is_transactional(
    engine: Engine,
) -> None:
    factory = sessionmaker(engine, expire_on_commit=False)
    ids = _seed_scope(factory)
    _evaluated_result(factory, ids)
    with Session(engine) as session:
        assert session.scalar(select(BaselineComparisonRow.attempt_id)) == ids["attempt"]
        rows = list(
            session.scalars(select(EvaluationRow).where(EvaluationRow.attempt_id == ids["attempt"]))
        )
        assert [row.ordinal for row in rows] == [0]
        assert session.scalar(select(TestAttemptRow.verdict)) == "passed"

    ids = _seed_scope(factory, seed=71000001)
    with pytest.raises(DatabaseError):
        with factory.begin() as session:
            attempt = session.get(TestAttemptRow, ids["attempt"])
            assert attempt is not None
            attempt.state = "evaluated"
            attempt.verdict = "passed"


def test_version_inheritance_and_replay_successor_are_database_enforced(
    engine: Engine,
) -> None:
    factory = sessionmaker(engine, expire_on_commit=False)
    ids = _seed_scope(factory)
    with pytest.raises(IntegrityError):
        with factory.begin() as session:
            session.add(
                TestAttemptRow(
                    id=uuid4(),
                    execution_item_id=ids["item"],
                    sequence=2,
                    result_contract_version=0,
                    state="prepared",
                    dispatch_certainty="not_started",
                    created_at=NOW,
                )
            )


def test_new_execution_materialization_pins_the_current_activation(engine: Engine) -> None:
    factory = sessionmaker(engine, expire_on_commit=False)
    ids = _seed_scope(factory, with_baseline=True)
    service = PostgresExecutionService(factory, clock=lambda: NOW)
    record = service.create(
        ExecutionCreateCommand(
            environment_id=ids["environment"],
            test_case_id=ids["test_case"],
        )
    )
    with Session(engine) as session:
        item = session.scalar(
            select(ExecutionItemRow).where(ExecutionItemRow.execution_id == record.id)
        )
        assert item is not None
        assert item.result_contract_version == 1
        assert item.baseline_activation_id == ids["activation"]
        assert item.baseline_id == ids["baseline"]


def test_baseline_scope_immutability_and_current_activation_uniqueness(
    engine: Engine,
) -> None:
    factory = sessionmaker(engine, expire_on_commit=False)
    ids = _seed_scope(factory, with_baseline=True)
    with pytest.raises(DatabaseError):
        with engine.begin() as connection:
            connection.execute(
                text("UPDATE baselines SET version = 2 WHERE id = :id"), {"id": ids["baseline"]}
            )
    with pytest.raises(IntegrityError):
        with factory.begin() as session:
            session.add(
                BaselineActivationRow(
                    id=uuid4(),
                    test_case_id=ids["test_case"],
                    environment_id=ids["environment"],
                    project_id=ids["project"],
                    baseline_id=ids["baseline"],
                    activated_at=NOW,
                )
            )
    with factory.begin() as session:
        current = session.get(BaselineActivationRow, ids["activation"])
        assert current is not None
        current.deactivated_at = NOW
    with pytest.raises(DatabaseError):
        with engine.begin() as connection:
            connection.execute(
                text("UPDATE baseline_activations SET reason = 'changed' WHERE id = :id"),
                {"id": ids["activation"]},
            )
    with pytest.raises(DatabaseError):
        with engine.begin() as connection:
            connection.execute(text("SET LOCAL sentinel.project_deletion = 'on'"))
            connection.execute(
                text("UPDATE baselines SET reason = 'changed' WHERE id = :id"),
                {"id": ids["baseline"]},
            )


def test_concurrent_activation_inserts_leave_one_current_row(engine: Engine) -> None:
    factory = sessionmaker(engine, expire_on_commit=False)
    ids = _seed_scope(factory, with_baseline=True)
    with factory.begin() as session:
        current = session.get(BaselineActivationRow, ids["activation"])
        assert current is not None
        current.deactivated_at = NOW

    def insert_activation(activation_id: UUID) -> bool:
        try:
            with factory.begin() as session:
                session.add(
                    BaselineActivationRow(
                        id=activation_id,
                        test_case_id=ids["test_case"],
                        environment_id=ids["environment"],
                        project_id=ids["project"],
                        baseline_id=ids["baseline"],
                        activated_at=NOW,
                    )
                )
            return True
        except IntegrityError:
            return False

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(lambda _: insert_activation(uuid4()), range(2)))
    assert sorted(outcomes) == [False, True]
    with Session(engine) as session:
        assert (
            session.scalar(
                select(text("count(*)"))
                .select_from(BaselineActivationRow)
                .where(
                    BaselineActivationRow.test_case_id == ids["test_case"],
                    BaselineActivationRow.environment_id == ids["environment"],
                    BaselineActivationRow.deactivated_at.is_(None),
                )
            )
            == 1
        )


def test_cross_project_baseline_pin_and_provenance_are_rejected(
    engine: Engine,
) -> None:
    factory = sessionmaker(engine, expire_on_commit=False)
    ids = _seed_scope(factory, with_baseline=True)
    other = _seed_scope(factory, seed=71000002)
    with pytest.raises(DatabaseError):
        with factory.begin() as session:
            item = session.get(ExecutionItemRow, other["item"])
            assert item is not None
            item.baseline_activation_id = ids["activation"]
            item.baseline_id = ids["baseline"]


def test_selected_value_and_evidence_bounds_are_explicit_and_safe() -> None:
    oversized = "x" * 4097
    assert bounded_evidence(oversized) == BoundedEvidence(None, True)
    assert bounded_evidence(None) == BoundedEvidence(None, False)
    with pytest.raises(PersistenceValidationError):
        validate_selected_values(
            {"schema_version": 1, "values": [{"rule_id": str(uuid4()), "value": oversized}]}
        )
    with pytest.raises(PersistenceValidationError):
        validate_selected_values(
            {
                "schema_version": 1,
                "values": [
                    {"rule_id": str(UUID("10000000-0000-4000-8000-000000000001")), "value": 1},
                    {"rule_id": str(UUID("10000000-0000-4000-8000-000000000001")), "value": 2},
                ],
            }
        )


def test_m4_upgrade_round_trip_preserves_legacy_m3_rows(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = engine.url.render_as_string(hide_password=False)
    monkeypatch.setenv("SENTINEL_DATABASE_URL", database_url)
    config = Config(str(Path(__file__).parents[2] / "alembic.ini"))
    legacy_id = UUID("72000000-0000-4000-8000-000000000001")
    downgrade(config, "0009")
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO executions (id,status,verdict,created_at,started_at,finished_at) "
                "VALUES (:id,'queued',NULL,now(),NULL,NULL)"
            ),
            {"id": legacy_id},
        )
    upgrade(config, "head")
    with engine.connect() as connection:
        assert (
            connection.scalar(
                text("SELECT result_contract_version FROM executions WHERE id = :id"),
                {"id": legacy_id},
            )
            == 0
        )
    downgrade(config, "0009")
    upgrade(config, "head")


def test_m4_result_read_projection_is_ordered_and_bounded(engine: Engine) -> None:
    factory = sessionmaker(engine, expire_on_commit=False)
    ids = _seed_scope(factory, seed=76000000)
    _evaluated_result(factory, ids)

    record = PostgresExecutionService(factory, clock=lambda: NOW).get_attempt(ids["attempt"])

    assert record is not None
    assert record.attempt.verdict == "passed"
    assert record.comparison is not None
    assert record.comparison.state == "not_requested"
    assert [evaluation.ordinal for evaluation in record.evaluations] == [0]
    assert record.evaluations[0].evidence_omitted is False


def test_m5_attempt_read_returns_scoped_ordered_bounded_trace_references(
    engine: Engine,
) -> None:
    factory = sessionmaker(engine, expire_on_commit=False)
    exporter = InMemorySpanExporter()
    tracer_provider = TracerProvider()
    tracer_provider.add_span_processor(SimpleSpanProcessor(exporter))
    ids = _seed_scope(factory, seed=76200000)
    with factory.begin() as session:
        session.add(
            TraceReferenceRow(
                id=UUID("76200000-0000-4000-8000-000000000010"),
                attempt_id=ids["attempt"],
                execution_item_id=ids["item"],
                execution_id=ids["execution"],
                project_id=ids["project"],
                relation="primary",
                trace_id="f" * 32,
                span_id="e" * 16,
                correlation_source="sentinel_context",
                status="pending",
                deadline_at=NOW,
                lookup_attempt_count=0,
                evidence_schema_version=1,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.add_all(
            [
                TraceReferenceRow(
                    id=UUID(f"76200000-0000-4000-8000-{index + 16:012x}"),
                    attempt_id=ids["attempt"],
                    execution_item_id=ids["item"],
                    execution_id=ids["execution"],
                    project_id=ids["project"],
                    relation="linked",
                    trace_id=f"{index:032x}",
                    span_id=None,
                    correlation_source="baggage_attribute_search",
                    status="available",
                    deadline_at=NOW,
                    lookup_attempt_count=1,
                    evidence_schema_version=1,
                    created_at=NOW,
                    updated_at=NOW,
                )
                for index in range(1, 18)
            ]
        )

    record = PostgresExecutionService(
        factory, clock=lambda: NOW, tracer=tracer_provider.get_tracer("sentinel.test")
    ).get_attempt(ids["attempt"])

    assert record is not None
    assert record.attempt.primary_trace_id == "d" * 32
    assert len(record.trace_references) == 17
    assert record.trace_references_truncated is True
    assert record.trace_references[0].relation == "primary"
    assert [reference.trace_id for reference in record.trace_references[1:]] == [
        f"{index:032x}" for index in range(1, 17)
    ]
    spans = exporter.get_finished_spans()
    assert [span.name for span in spans] == ["sentinel.db.operation"]
    assert spans[0].attributes == {"sentinel.operation.kind": "attempt.read"}


def test_m4_execution_detail_reads_change_evidence_without_raw_values(engine: Engine) -> None:
    factory = sessionmaker(engine, expire_on_commit=False)
    ids = _seed_scope(factory, seed=76100000)
    _evaluated_result(factory, ids)

    record = PostgresExecutionService(factory, clock=lambda: NOW).get(ids["execution"])

    assert record is not None
    assert record.pinned_change_events == ()
    assert record.change_evidence.events == ()

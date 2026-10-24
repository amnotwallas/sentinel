from __future__ import annotations

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from sqlalchemy import func, select, text, update
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from sentinel.catalog.definitions import DefinitionValidationError
from sentinel.execution.attempts import ResponseArtifact
from sentinel.execution.creation import ExecutionCreateCommand, PostgresExecutionService
from sentinel.execution.domain import (
    DispatchCertainty,
    LeaseLost,
    PreparationErrorCode,
    RedirectRejectionCode,
    TransportOutcome,
)
from sentinel.execution.orchestration import ExecutionOrchestrator
from sentinel.execution.ports import CancellationSignal, TransportResult
from sentinel.execution.preparation import PreparedRequest
from sentinel.persistence.attempts import PostgresAttemptStore
from sentinel.persistence.models import (
    BaselineActivationRow,
    BaselineComparisonRow,
    BaselineRow,
    EnvironmentRevisionRow,
    EnvironmentRow,
    EvaluationRow,
    ExecutionItemRow,
    ExecutionRow,
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
from sentinel.persistence.orchestration import OrchestrationConflict, PostgresOrchestrationStore
from sentinel.persistence.queue import PostgresJobStore
from sentinel.security.definition_policy import validate_test_definition
from sentinel.security.secrets import EnvironmentSecretResolver
from sentinel.telemetry.execution import OpenTelemetryTraceLifecycle
from tests.conftest import Clock

pytestmark = pytest.mark.integration
NOW = datetime(2030, 1, 1, tzinfo=UTC)
PROJECT_ID = UUID("50000000-0000-4000-8000-000000000001")
ENVIRONMENT_ID = UUID("50000000-0000-4000-8000-000000000002")
ENVIRONMENT_REVISION_ID = UUID("50000000-0000-4000-8000-000000000003")
CASE_ONE_ID = UUID("50000000-0000-4000-8000-000000000004")
CASE_ONE_REVISION_ID = UUID("50000000-0000-4000-8000-000000000005")
CASE_TWO_ID = UUID("50000000-0000-4000-8000-000000000006")
CASE_TWO_REVISION_ID = UUID("50000000-0000-4000-8000-000000000007")
SUITE_ID = UUID("50000000-0000-4000-8000-000000000008")
SUITE_REVISION_ID = UUID("50000000-0000-4000-8000-000000000009")


def definition(method: str = "GET", path: str = "/one", **extra: object) -> dict[str, object]:
    return {
        "schema_version": 1,
        "request": {"method": method, "path": path},
        **extra,
    }


@pytest.fixture
def seeded_orchestration_catalog(engine: Engine) -> None:
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory.begin() as session:
        session.add(
            ProjectRow(id=PROJECT_ID, name="orchestration", state_version=1, created_at=NOW)
        )
        session.flush()
        session.add_all(
            [
                EnvironmentRow(
                    id=ENVIRONMENT_ID,
                    project_id=PROJECT_ID,
                    name="env",
                    active_revision_id=ENVIRONMENT_REVISION_ID,
                    state_version=1,
                    created_at=NOW,
                    updated_at=NOW,
                ),
                TestCaseRow(
                    id=CASE_ONE_ID,
                    project_id=PROJECT_ID,
                    name="one",
                    active_revision_id=CASE_ONE_REVISION_ID,
                    state_version=1,
                    created_at=NOW,
                    updated_at=NOW,
                ),
                TestCaseRow(
                    id=CASE_TWO_ID,
                    project_id=PROJECT_ID,
                    name="two",
                    active_revision_id=CASE_TWO_REVISION_ID,
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
                    definition={
                        "schema_version": 1,
                        "base_url": "https://api.example.test/",
                        "variables": {},
                        "secret_references": [],
                        "target_policy": {},
                    },
                    created_at=NOW,
                ),
                TestCaseRevisionRow(
                    id=CASE_ONE_REVISION_ID,
                    test_case_id=CASE_ONE_ID,
                    version=1,
                    definition=definition(path="/one"),
                    policy_fingerprint="a" * 64,
                    created_at=NOW,
                ),
                TestCaseRevisionRow(
                    id=CASE_TWO_REVISION_ID,
                    test_case_id=CASE_TWO_ID,
                    version=1,
                    definition=definition(path="/two"),
                    policy_fingerprint="b" * 64,
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
                    test_case_id=CASE_ONE_ID,
                    test_case_revision_id=CASE_ONE_REVISION_ID,
                    test_case_revision_version=1,
                ),
                SuiteRevisionItemRow(
                    suite_revision_id=SUITE_REVISION_ID,
                    ordinal=1,
                    project_id=PROJECT_ID,
                    test_case_id=CASE_TWO_ID,
                    test_case_revision_id=CASE_TWO_REVISION_ID,
                    test_case_revision_version=1,
                ),
            ]
        )


class ScriptedTransport:
    def __init__(self, results: Iterator[TransportResult]) -> None:
        self.results = results
        self.requests: list[PreparedRequest] = []

    def dispatch(self, request: PreparedRequest) -> TransportResult:
        self.requests.append(request)
        return next(self.results)

    def dispatch_cancellable(
        self, request: PreparedRequest, cancellation: CancellationSignal
    ) -> TransportResult:
        cancellation.raise_if_cancelled()
        return self.dispatch(request)


def response(body: object, *, kind: str = "json") -> TransportResult:
    return TransportResult(
        TransportOutcome.RESPONSE_RECEIVED,
        DispatchCertainty.RESPONSE_RECEIVED,
        200,
        {},
        b"bounded",
        7,
        False,
        body_kind=kind,
        body_content=body,
    )


def telemetry() -> OpenTelemetryTraceLifecycle:
    provider = TracerProvider()
    return OpenTelemetryTraceLifecycle(provider.get_tracer("sentinel.test.orchestration"))


def recording_telemetry() -> tuple[OpenTelemetryTraceLifecycle, InMemorySpanExporter]:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return (
        OpenTelemetryTraceLifecycle(provider.get_tracer("sentinel.test.orchestration")),
        exporter,
    )


def create_execution(engine: Engine, *, suite: bool = False) -> tuple[UUID, PostgresJobStore]:
    factory = sessionmaker(engine, expire_on_commit=False)
    service = PostgresExecutionService(factory, clock=lambda: NOW)
    command = (
        ExecutionCreateCommand(ENVIRONMENT_ID, suite_id=SUITE_ID)
        if suite
        else ExecutionCreateCommand(ENVIRONMENT_ID, test_case_id=CASE_ONE_ID)
    )
    execution = service.create(command)
    return execution.id, PostgresJobStore(factory, clock=lambda: NOW)


def test_ordered_suite_reaches_atomic_terminal_state(
    engine: Engine, seeded_orchestration_catalog: None
) -> None:
    execution_id, jobs = create_execution(engine, suite=True)
    lease = jobs.claim(uuid4(), 60)
    assert lease is not None
    store = PostgresOrchestrationStore(
        sessionmaker(engine, expire_on_commit=False), clock=lambda: NOW
    )
    transport = ScriptedTransport(iter([response({"case": 1}), response({"case": 2})]))
    traces, exporter = recording_telemetry()

    ExecutionOrchestrator(
        store, transport, EnvironmentSecretResolver({}), traces, clock=lambda: NOW
    ).run(lease)

    assert [request.url for request in transport.requests] == [
        "https://api.example.test/one",
        "https://api.example.test/two",
    ]
    with Session(engine) as session:
        execution = session.get(ExecutionRow, execution_id)
        items = list(
            session.scalars(
                select(ExecutionItemRow)
                .where(ExecutionItemRow.execution_id == execution_id)
                .order_by(ExecutionItemRow.ordinal)
            )
        )
        job = session.get(JobRow, lease.job_id)
        attempts = list(
            session.scalars(
                select(TestAttemptRow)
                .join(ExecutionItemRow)
                .where(ExecutionItemRow.execution_id == execution_id)
                .order_by(ExecutionItemRow.ordinal)
            )
        )
    assert execution is not None and (execution.status, execution.verdict) == (
        "completed",
        "passed",
    )
    assert [(item.ordinal, item.status, item.verdict) for item in items] == [
        (0, "completed", "passed"),
        (1, "completed", "passed"),
    ]
    assert job is not None and job.state == "succeeded"
    finished = exporter.get_finished_spans()
    assert len(finished) == 2
    assert [attempt.primary_trace_id for attempt in attempts] == [
        f"{span.context.trace_id:032x}" for span in finished
    ]
    assert [attempt.client_span_id for attempt in attempts] == [
        f"{span.context.span_id:016x}" for span in finished
    ]


def test_version1_response_is_evaluated_and_aggregated(
    engine: Engine, seeded_orchestration_catalog: None
) -> None:
    execution_id, jobs = create_execution(engine)
    lease = jobs.claim(uuid4(), 60)
    assert lease is not None
    transport = ScriptedTransport(iter([response({"ok": True})]))

    ExecutionOrchestrator(
        PostgresOrchestrationStore(sessionmaker(engine, expire_on_commit=False), clock=lambda: NOW),
        transport,
        EnvironmentSecretResolver({}),
        telemetry(),
        clock=lambda: NOW,
    ).run(lease)

    with Session(engine) as session:
        execution = session.get(ExecutionRow, execution_id)
        item = session.scalar(
            select(ExecutionItemRow).where(ExecutionItemRow.execution_id == execution_id)
        )
        attempt = (
            session.scalar(
                select(TestAttemptRow).where(TestAttemptRow.execution_item_id == item.id)
            )
            if item is not None
            else None
        )
        comparison_count = session.scalar(
            select(func.count(BaselineComparisonRow.attempt_id)).where(
                BaselineComparisonRow.attempt_id == attempt.id
                if attempt is not None
                else text("false")
            )
        )
        evaluation_count = session.scalar(
            select(func.count(EvaluationRow.id)).where(
                EvaluationRow.attempt_id == attempt.id if attempt is not None else text("false")
            )
        )

    assert execution is not None and (execution.status, execution.verdict) == (
        "completed",
        "passed",
    )
    assert item is not None and (item.status, item.verdict) == ("completed", "passed")
    assert attempt is not None and (attempt.state, attempt.verdict) == ("evaluated", "passed")
    assert comparison_count == 1
    assert evaluation_count == 0


def test_required_failure_precedes_advisory_failure_in_durable_aggregation(
    engine: Engine, seeded_orchestration_catalog: None
) -> None:
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory.begin() as session:
        session.execute(
            update(TestCaseRevisionRow)
            .where(TestCaseRevisionRow.id == CASE_ONE_REVISION_ID)
            .values(
                definition=definition(
                    assertions=[
                        {
                            "id": "00000000-0000-4000-8000-000000000101",
                            "severity": "required",
                            "kind": "status_code",
                            "expected_codes": [201],
                        },
                        {
                            "id": "00000000-0000-4000-8000-000000000102",
                            "severity": "advisory",
                            "kind": "header_equals",
                            "header_name": "X-Change",
                            "expected": "new",
                        },
                    ]
                )
            )
        )
    execution_id, jobs = create_execution(engine)
    lease = jobs.claim(uuid4(), 60)
    assert lease is not None
    transport = ScriptedTransport(
        iter(
            [
                TransportResult(
                    TransportOutcome.RESPONSE_RECEIVED,
                    DispatchCertainty.RESPONSE_RECEIVED,
                    500,
                    {"x-change": "old"},
                    b"",
                    0,
                    False,
                )
            ]
        )
    )

    ExecutionOrchestrator(
        PostgresOrchestrationStore(factory, clock=lambda: NOW),
        transport,
        EnvironmentSecretResolver({}),
        telemetry(),
        clock=lambda: NOW,
    ).run(lease)

    with Session(engine) as session:
        execution = session.get(ExecutionRow, execution_id)
        item = session.scalar(
            select(ExecutionItemRow).where(ExecutionItemRow.execution_id == execution_id)
        )
        attempt = (
            session.scalar(
                select(TestAttemptRow).where(TestAttemptRow.execution_item_id == item.id)
            )
            if item is not None
            else None
        )
        evaluations = list(
            session.scalars(
                select(EvaluationRow)
                .where(
                    EvaluationRow.attempt_id == attempt.id if attempt is not None else text("false")
                )
                .order_by(EvaluationRow.ordinal)
            )
        )
    assert execution is not None and execution.verdict == "functional_regression"
    assert item is not None and item.verdict == "functional_regression"
    assert attempt is not None and attempt.verdict == "functional_regression"
    assert [(row.ordinal, row.severity, row.outcome) for row in evaluations] == [
        (0, "required", "failed"),
        (1, "advisory", "failed"),
    ]


def test_pinned_baseline_is_used_for_evaluation_and_recorded(
    engine: Engine, seeded_orchestration_catalog: None
) -> None:
    factory = sessionmaker(engine, expire_on_commit=False)
    rule_id = "00000000-0000-4000-8000-000000000103"
    document = definition(
        comparison_policy={
            "selectors": [
                {
                    "id": rule_id,
                    "severity": "required",
                    "pointer": "/value",
                    "normalizer": {"name": "none", "version": 1},
                }
            ]
        }
    )
    fingerprint = validate_test_definition(document).policy_fingerprint
    baseline_id = UUID("50000000-0000-4000-8000-000000000104")
    activation_id = UUID("50000000-0000-4000-8000-000000000105")
    with factory.begin() as session:
        session.execute(
            update(TestCaseRevisionRow)
            .where(TestCaseRevisionRow.id == CASE_ONE_REVISION_ID)
            .values(definition=document, policy_fingerprint=fingerprint)
        )
        session.flush()
        session.add(
            BaselineRow(
                id=baseline_id,
                test_case_id=CASE_ONE_ID,
                environment_id=ENVIRONMENT_ID,
                project_id=PROJECT_ID,
                version=1,
                source_attempt_id=uuid4(),
                source_execution_id=uuid4(),
                source_test_case_revision_id=CASE_ONE_REVISION_ID,
                source_attempt_verdict="baseline_required",
                source_finished_at=NOW,
                policy_fingerprint=fingerprint,
                selected_values_schema_version=1,
                selected_values={
                    "schema_version": 1,
                    "values": [{"rule_id": rule_id, "value": Decimal("1.00")}],
                },
                created_at=NOW,
            )
        )
        session.flush()
        session.add(
            BaselineActivationRow(
                id=activation_id,
                test_case_id=CASE_ONE_ID,
                environment_id=ENVIRONMENT_ID,
                project_id=PROJECT_ID,
                baseline_id=baseline_id,
                activated_at=NOW,
            )
        )

    execution_id, jobs = create_execution(engine)
    lease = jobs.claim(uuid4(), 60)
    assert lease is not None
    transport = ScriptedTransport(iter([response({"value": Decimal("1.00")})]))
    ExecutionOrchestrator(
        PostgresOrchestrationStore(factory, clock=lambda: NOW),
        transport,
        EnvironmentSecretResolver({}),
        telemetry(),
        clock=lambda: NOW,
    ).run(lease)

    with Session(engine) as session:
        execution = session.get(ExecutionRow, execution_id)
        item = session.scalar(
            select(ExecutionItemRow).where(ExecutionItemRow.execution_id == execution_id)
        )
        attempt = (
            session.scalar(
                select(TestAttemptRow).where(TestAttemptRow.execution_item_id == item.id)
            )
            if item is not None
            else None
        )
        comparison = session.get(BaselineComparisonRow, attempt.id) if attempt is not None else None
    assert execution is not None and execution.verdict == "passed"
    assert item is not None and item.baseline_activation_id == activation_id
    assert item.baseline_id == baseline_id
    assert attempt is not None and attempt.verdict == "passed"
    assert comparison is not None and (
        comparison.state,
        comparison.baseline_id,
        comparison.baseline_version,
        comparison.policy_fingerprint,
    ) == ("compatible", baseline_id, 1, fingerprint)


def test_preparation_failure_continues_to_next_ordered_item(
    engine: Engine, seeded_orchestration_catalog: None
) -> None:
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory.begin() as session:
        session.execute(
            update(EnvironmentRevisionRow)
            .where(EnvironmentRevisionRow.id == ENVIRONMENT_REVISION_ID)
            .values(
                definition={
                    "schema_version": 1,
                    "base_url": "https://api.example.test/",
                    "variables": {},
                    "secret_references": [{"$secret": "API_TOKEN"}],
                    "target_policy": {},
                }
            )
        )
        session.execute(
            update(TestCaseRevisionRow)
            .where(TestCaseRevisionRow.id == CASE_ONE_REVISION_ID)
            .values(
                definition={
                    "schema_version": 1,
                    "request": {
                        "method": "GET",
                        "path": "/one",
                        "headers": [{"name": "Authorization", "value": {"$secret": "API_TOKEN"}}],
                    },
                }
            )
        )
    execution_id, jobs = create_execution(engine, suite=True)
    lease = jobs.claim(uuid4(), 60)
    assert lease is not None
    transport = ScriptedTransport(iter([response("second", kind="text")]))

    ExecutionOrchestrator(
        PostgresOrchestrationStore(factory, clock=lambda: NOW),
        transport,
        EnvironmentSecretResolver({}),
        telemetry(),
        clock=lambda: NOW,
    ).run(lease)

    assert [request.url for request in transport.requests] == ["https://api.example.test/two"]
    with Session(engine) as session:
        items = list(
            session.scalars(
                select(ExecutionItemRow)
                .where(ExecutionItemRow.execution_id == execution_id)
                .order_by(ExecutionItemRow.ordinal)
            )
        )
    assert [(item.status, item.verdict) for item in items] == [
        ("failed", "not_evaluated"),
        ("completed", "passed"),
    ]


def test_crash_before_dispatch_resumes_same_prepared_attempt(
    engine: Engine, seeded_orchestration_catalog: None, clock: Clock
) -> None:
    factory = sessionmaker(engine, expire_on_commit=False)
    execution = PostgresExecutionService(factory, clock=clock).create(
        ExecutionCreateCommand(ENVIRONMENT_ID, test_case_id=CASE_ONE_ID)
    )
    jobs = PostgresJobStore(factory, clock=clock)
    first_lease = jobs.claim(uuid4(), 60)
    assert first_lease is not None
    store = PostgresOrchestrationStore(factory, clock=clock)
    prepared = store.acquire_next(first_lease, attempt_id=uuid4())
    assert prepared is not None
    clock.advance(60)
    recovered = jobs.claim(uuid4(), 60)
    assert recovered is not None
    transport = ScriptedTransport(iter([response("ok", kind="text")]))

    ExecutionOrchestrator(
        store, transport, EnvironmentSecretResolver({}), telemetry(), clock=clock
    ).run(recovered)

    with Session(engine) as session:
        attempts = list(
            session.scalars(
                select(TestAttemptRow)
                .join(ExecutionItemRow)
                .where(ExecutionItemRow.execution_id == execution.id)
            )
        )
    assert len(attempts) == 1 and attempts[0].id == prepared.attempt.id
    assert attempts[0].state == "evaluated"
    assert len(transport.requests) == 1


def test_orchestration_loads_exact_pinned_revisions_not_active_replacements(
    engine: Engine, seeded_orchestration_catalog: None
) -> None:
    execution_id, jobs = create_execution(engine)
    replacement_environment_id = UUID("50000000-0000-4000-8000-000000000101")
    replacement_case_id = UUID("50000000-0000-4000-8000-000000000102")
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory.begin() as session:
        session.add_all(
            [
                EnvironmentRevisionRow(
                    id=replacement_environment_id,
                    environment_id=ENVIRONMENT_ID,
                    version=2,
                    definition={
                        "schema_version": 1,
                        "base_url": "https://replacement.example.test/",
                        "variables": {},
                        "secret_references": [],
                        "target_policy": {},
                    },
                    created_at=NOW,
                ),
                TestCaseRevisionRow(
                    id=replacement_case_id,
                    test_case_id=CASE_ONE_ID,
                    version=2,
                    definition=definition(path="/replacement"),
                    policy_fingerprint="c" * 64,
                    created_at=NOW,
                ),
            ]
        )
        session.flush()
        session.execute(
            update(EnvironmentRow)
            .where(EnvironmentRow.id == ENVIRONMENT_ID)
            .values(active_revision_id=replacement_environment_id, state_version=2)
        )
        session.execute(
            update(TestCaseRow)
            .where(TestCaseRow.id == CASE_ONE_ID)
            .values(active_revision_id=replacement_case_id, state_version=2)
        )
    lease = jobs.claim(uuid4(), 60)
    assert lease is not None
    transport = ScriptedTransport(iter([response("pinned", kind="text")]))

    ExecutionOrchestrator(
        PostgresOrchestrationStore(factory, clock=lambda: NOW),
        transport,
        EnvironmentSecretResolver({}),
        telemetry(),
        clock=lambda: NOW,
    ).run(lease)

    assert [request.url for request in transport.requests] == ["https://api.example.test/one"]
    with Session(engine) as session:
        item = session.scalar(
            select(ExecutionItemRow).where(ExecutionItemRow.execution_id == execution_id)
        )
    assert item is not None and item.test_case_revision_id == CASE_ONE_REVISION_ID


def test_response_checkpoint_recovery_never_redispatches(
    engine: Engine, seeded_orchestration_catalog: None, clock: Clock
) -> None:
    factory = sessionmaker(engine, expire_on_commit=False)
    execution = PostgresExecutionService(factory, clock=clock).create(
        ExecutionCreateCommand(ENVIRONMENT_ID, test_case_id=CASE_ONE_ID)
    )
    jobs = PostgresJobStore(factory, clock=clock)
    first_lease = jobs.claim(uuid4(), 60)
    assert first_lease is not None
    orchestration = PostgresOrchestrationStore(factory, clock=clock)
    work = orchestration.acquire_next(first_lease, attempt_id=uuid4())
    assert work is not None
    attempts = PostgresAttemptStore(factory, clock=clock)
    attempts.checkpoint_dispatch(
        work.attempt.id,
        first_lease,
        fingerprint="a" * 64,
        trace_id="b" * 32,
        span_id="c" * 16,
    )
    attempts.record_response(
        work.attempt.id,
        first_lease,
        ResponseArtifact(
            work.attempt.id,
            200,
            {},
            "text",
            "stored",
            6,
            False,
            False,
            clock.value,
            clock.value + timedelta(days=7),
        ),
        outcome=TransportOutcome.RESPONSE_RECEIVED,
    )
    clock.advance(60)
    recovered = jobs.claim(uuid4(), 60)
    assert recovered is not None
    transport = ScriptedTransport(iter([]))

    ExecutionOrchestrator(
        orchestration, transport, EnvironmentSecretResolver({}), telemetry(), clock=clock
    ).run(recovered)

    assert transport.requests == []
    with Session(engine) as session:
        execution_row = session.get(ExecutionRow, execution.id)
        job = session.get(JobRow, recovered.job_id)
    assert execution_row is not None and execution_row.status == "completed"
    assert job is not None and job.state == "succeeded"


def test_delivery_exhaustion_fails_pending_v1_evaluation_atomically(
    engine: Engine, seeded_orchestration_catalog: None, clock: Clock
) -> None:
    factory = sessionmaker(engine, expire_on_commit=False)
    execution = PostgresExecutionService(factory, clock=clock).create(
        ExecutionCreateCommand(ENVIRONMENT_ID, test_case_id=CASE_ONE_ID)
    )
    jobs = PostgresJobStore(factory, clock=clock)
    with factory.begin() as session:
        session.execute(
            update(JobRow).where(JobRow.subject_id == execution.id).values(max_deliveries=1)
        )
    first_lease = jobs.claim(uuid4(), 60)
    assert first_lease is not None
    orchestration = PostgresOrchestrationStore(factory, clock=clock)
    work = orchestration.acquire_next(first_lease, attempt_id=uuid4())
    assert work is not None
    attempts = PostgresAttemptStore(factory, clock=clock)
    attempts.checkpoint_dispatch(
        work.attempt.id,
        first_lease,
        fingerprint="a" * 64,
        trace_id="b" * 32,
        span_id="c" * 16,
    )
    attempts.record_response(
        work.attempt.id,
        first_lease,
        ResponseArtifact(
            work.attempt.id,
            200,
            {},
            "json",
            {"ok": True},
            11,
            False,
            False,
            clock.value,
            clock.value + timedelta(days=7),
        ),
        outcome=TransportOutcome.RESPONSE_RECEIVED,
    )

    clock.advance(60)
    assert jobs.claim(uuid4(), 60) is None

    with Session(engine) as session:
        execution_row = session.get(ExecutionRow, execution.id)
        item = session.scalar(
            select(ExecutionItemRow).where(ExecutionItemRow.execution_id == execution.id)
        )
        attempt = (
            session.scalar(
                select(TestAttemptRow).where(TestAttemptRow.execution_item_id == item.id)
            )
            if item is not None
            else None
        )
        job = session.scalar(select(JobRow).where(JobRow.subject_id == execution.id))
        comparison_count = session.scalar(
            select(func.count(BaselineComparisonRow.attempt_id)).where(
                BaselineComparisonRow.attempt_id == attempt.id
                if attempt is not None
                else text("false")
            )
        )
        evaluation_count = session.scalar(
            select(func.count(EvaluationRow.id)).where(
                EvaluationRow.attempt_id == attempt.id if attempt is not None else text("false")
            )
        )
    assert execution_row is not None and (execution_row.status, execution_row.verdict) == (
        "failed",
        "inconclusive",
    )
    assert item is not None and (item.status, item.verdict) == ("failed", "inconclusive")
    assert attempt is not None and (
        attempt.state,
        attempt.verdict,
        attempt.evaluation_error_code,
    ) == ("failed", "inconclusive", "platform_evaluation_failure")
    assert job is not None and job.state == "dead"
    assert comparison_count == 0
    assert evaluation_count == 0


def test_transport_failure_checkpoint_recovery_never_redispatches(
    engine: Engine, seeded_orchestration_catalog: None, clock: Clock
) -> None:
    factory = sessionmaker(engine, expire_on_commit=False)
    execution = PostgresExecutionService(factory, clock=clock).create(
        ExecutionCreateCommand(ENVIRONMENT_ID, test_case_id=CASE_ONE_ID)
    )
    jobs = PostgresJobStore(factory, clock=clock)
    first_lease = jobs.claim(uuid4(), 60)
    assert first_lease is not None
    orchestration = PostgresOrchestrationStore(factory, clock=clock)
    work = orchestration.acquire_next(first_lease, attempt_id=uuid4())
    assert work is not None
    attempts = PostgresAttemptStore(factory, clock=clock)
    attempts.checkpoint_dispatch(
        work.attempt.id,
        first_lease,
        fingerprint="a" * 64,
        trace_id="b" * 32,
        span_id="c" * 16,
    )
    attempts.record_transport_failure(
        work.attempt.id,
        first_lease,
        outcome=TransportOutcome.DNS_FAILURE,
        certainty=DispatchCertainty.NOT_SENT,
        not_sent_proof="dns_failure",
    )
    clock.advance(60)
    recovered = jobs.claim(uuid4(), 60)
    assert recovered is not None
    transport = ScriptedTransport(iter([]))

    ExecutionOrchestrator(
        orchestration, transport, EnvironmentSecretResolver({}), telemetry(), clock=clock
    ).run(recovered)

    assert transport.requests == []
    with Session(engine) as session:
        execution_row = session.get(ExecutionRow, execution.id)
        item = session.scalar(
            select(ExecutionItemRow).where(ExecutionItemRow.execution_id == execution.id)
        )
        job = session.get(JobRow, recovered.job_id)
    assert execution_row is not None and execution_row.status == "completed"
    assert item is not None and (item.status, item.verdict) == (
        "completed",
        "inconclusive",
    )
    assert job is not None and job.state == "succeeded"


def test_safe_recovery_creates_one_fresh_linked_successor(
    engine: Engine, seeded_orchestration_catalog: None, clock: Clock
) -> None:
    factory = sessionmaker(engine, expire_on_commit=False)
    execution = PostgresExecutionService(factory, clock=clock).create(
        ExecutionCreateCommand(ENVIRONMENT_ID, test_case_id=CASE_ONE_ID)
    )
    jobs = PostgresJobStore(factory, clock=clock)
    lease = jobs.claim(uuid4(), 60)
    assert lease is not None
    store = PostgresOrchestrationStore(factory, clock=clock)
    first = store.acquire_next(lease, attempt_id=uuid4())
    assert first is not None
    store.checkpoint_dispatch(
        first.attempt.id,
        lease,
        fingerprint="a" * 64,
        trace_id="b" * 32,
        span_id="c" * 16,
    )
    clock.advance(60)
    recovered = jobs.claim(uuid4(), 60)
    assert recovered is not None
    successor_id = UUID("60000000-0000-4000-8000-000000000001")
    transport = ScriptedTransport(iter([response("recovered", kind="text")]))
    ids = iter([uuid4(), successor_id, uuid4(), uuid4()])

    ExecutionOrchestrator(
        store,
        transport,
        EnvironmentSecretResolver({}),
        telemetry(),
        attempt_ids=lambda: next(ids),
        clock=clock,
    ).run(recovered)

    with Session(engine) as session:
        attempts = list(
            session.scalars(
                select(TestAttemptRow)
                .join(ExecutionItemRow)
                .where(ExecutionItemRow.execution_id == execution.id)
                .order_by(TestAttemptRow.sequence)
            )
        )
    assert [(item.id, item.state, item.replay_successor_id) for item in attempts] == [
        (first.attempt.id, "replay_scheduled", successor_id),
        (successor_id, "evaluated", None),
    ]
    assert attempts[0].primary_trace_id != attempts[1].primary_trace_id
    assert attempts[0].client_span_id != attempts[1].client_span_id
    assert len(transport.requests) == 1


def test_acknowledged_unsafe_recovery_creates_fresh_successor(
    engine: Engine, seeded_orchestration_catalog: None, clock: Clock
) -> None:
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory.begin() as session:
        session.execute(
            update(TestCaseRevisionRow)
            .where(TestCaseRevisionRow.id == CASE_ONE_REVISION_ID)
            .values(
                definition=definition("POST", "/charge", allow_unsafe_replay=True),
                unsafe_replay_acknowledgement="duplicate_effects_possible",
                unsafe_replay_acknowledged_at=NOW,
            )
        )
    execution = PostgresExecutionService(factory, clock=clock).create(
        ExecutionCreateCommand(ENVIRONMENT_ID, test_case_id=CASE_ONE_ID)
    )
    jobs = PostgresJobStore(factory, clock=clock)
    lease = jobs.claim(uuid4(), 60)
    assert lease is not None
    store = PostgresOrchestrationStore(factory, clock=clock)
    first = store.acquire_next(lease, attempt_id=uuid4())
    assert first is not None
    store.checkpoint_dispatch(
        first.attempt.id,
        lease,
        fingerprint="a" * 64,
        trace_id="b" * 32,
        span_id="c" * 16,
    )
    clock.advance(60)
    recovered = jobs.claim(uuid4(), 60)
    assert recovered is not None
    transport = ScriptedTransport(iter([response("unsafe-replay", kind="text")]))

    ExecutionOrchestrator(
        store,
        transport,
        EnvironmentSecretResolver({}),
        telemetry(),
        clock=clock,
    ).run(recovered)

    with Session(engine) as session:
        attempts = list(
            session.scalars(
                select(TestAttemptRow)
                .join(ExecutionItemRow)
                .where(ExecutionItemRow.execution_id == execution.id)
                .order_by(TestAttemptRow.sequence)
            )
        )
    assert [attempt.state for attempt in attempts] == ["replay_scheduled", "evaluated"]
    assert attempts[0].replay_successor_id == attempts[1].id
    assert attempts[0].primary_trace_id != attempts[1].primary_trace_id
    assert attempts[0].client_span_id != attempts[1].client_span_id
    assert len(transport.requests) == 1


def test_unsafe_ambiguity_is_inconclusive_and_skips_only_pending_items(
    engine: Engine, seeded_orchestration_catalog: None, clock: Clock
) -> None:
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory.begin() as session:
        session.execute(
            update(TestCaseRevisionRow)
            .where(TestCaseRevisionRow.id == CASE_ONE_REVISION_ID)
            .values(definition=definition("POST", "/charge", allow_unsafe_replay=True))
        )
    execution = PostgresExecutionService(factory, clock=clock).create(
        ExecutionCreateCommand(ENVIRONMENT_ID, suite_id=SUITE_ID)
    )
    jobs = PostgresJobStore(factory, clock=clock)
    lease = jobs.claim(uuid4(), 60)
    assert lease is not None
    store = PostgresOrchestrationStore(factory, clock=clock)
    first = store.acquire_next(lease, attempt_id=uuid4())
    assert first is not None
    store.checkpoint_dispatch(
        first.attempt.id,
        lease,
        fingerprint="a" * 64,
        trace_id="b" * 32,
        span_id="c" * 16,
    )
    clock.advance(60)
    recovered = jobs.claim(uuid4(), 60)
    assert recovered is not None
    transport = ScriptedTransport(iter([]))

    ExecutionOrchestrator(
        store, transport, EnvironmentSecretResolver({}), telemetry(), clock=clock
    ).run(recovered)

    with Session(engine) as session:
        execution_row = session.get(ExecutionRow, execution.id)
        items = list(
            session.scalars(
                select(ExecutionItemRow)
                .where(ExecutionItemRow.execution_id == execution.id)
                .order_by(ExecutionItemRow.ordinal)
            )
        )
        attempt_row = session.get(TestAttemptRow, first.attempt.id)
        job = session.get(JobRow, recovered.job_id)
    assert attempt_row is not None and attempt_row.state == "indeterminate"
    assert [(item.status, item.verdict) for item in items] == [
        ("indeterminate", "inconclusive"),
        ("skipped", "not_evaluated"),
    ]
    assert execution_row is not None and (execution_row.status, execution_row.verdict) == (
        "completed",
        "inconclusive",
    )
    assert job is not None and job.state == "succeeded"
    assert transport.requests == []


@pytest.mark.parametrize(
    ("result", "expected_item", "expected_verdict"),
    [
        (
            TransportResult(
                TransportOutcome.TARGET_DENIED,
                DispatchCertainty.NOT_SENT,
                None,
                {},
                None,
                0,
                False,
                not_sent_proof="target_denied",
            ),
            "failed",
            "not_evaluated",
        ),
        (
            TransportResult(
                TransportOutcome.TLS_FAILURE,
                DispatchCertainty.NOT_SENT,
                None,
                {},
                None,
                0,
                False,
                not_sent_proof="tls_failure",
            ),
            "failed",
            "not_evaluated",
        ),
        (
            TransportResult(
                TransportOutcome.DNS_FAILURE,
                DispatchCertainty.NOT_SENT,
                None,
                {},
                None,
                0,
                False,
                not_sent_proof="dns_failure",
            ),
            "completed",
            "inconclusive",
        ),
        (
            TransportResult(
                TransportOutcome.WRITE_FAILURE,
                DispatchCertainty.POSSIBLY_SENT,
                None,
                {},
                None,
                0,
                False,
            ),
            "completed",
            "inconclusive",
        ),
    ],
)
def test_transport_outcome_aggregation_is_stable_and_never_retries(
    engine: Engine,
    seeded_orchestration_catalog: None,
    result: TransportResult,
    expected_item: str,
    expected_verdict: str,
) -> None:
    execution_id, jobs = create_execution(engine)
    lease = jobs.claim(uuid4(), 60)
    assert lease is not None
    transport = ScriptedTransport(iter([result]))

    ExecutionOrchestrator(
        PostgresOrchestrationStore(sessionmaker(engine, expire_on_commit=False), clock=lambda: NOW),
        transport,
        EnvironmentSecretResolver({}),
        telemetry(),
        clock=lambda: NOW,
    ).run(lease)

    with Session(engine) as session:
        item = session.scalar(
            select(ExecutionItemRow).where(ExecutionItemRow.execution_id == execution_id)
        )
        attempt = session.scalar(
            select(TestAttemptRow)
            .join(ExecutionItemRow)
            .where(ExecutionItemRow.execution_id == execution_id)
        )
    assert item is not None and (item.status, item.verdict) == (
        expected_item,
        expected_verdict,
    )
    assert attempt is not None and attempt.state == "transport_failed"
    assert len(transport.requests) == 1


def test_rejected_redirect_persists_only_bounded_sanitized_evidence(
    engine: Engine, seeded_orchestration_catalog: None
) -> None:
    execution_id, jobs = create_execution(engine)
    lease = jobs.claim(uuid4(), 60)
    assert lease is not None
    transport = ScriptedTransport(
        iter(
            [
                TransportResult(
                    TransportOutcome.REDIRECT_DENIED,
                    DispatchCertainty.RESPONSE_RECEIVED,
                    302,
                    {"location": "[REDACTED]"},
                    b"redirect",
                    8,
                    False,
                    RedirectRejectionCode.TARGET_DENIED,
                    body_kind="text",
                    body_content="redirect",
                )
            ]
        )
    )

    ExecutionOrchestrator(
        PostgresOrchestrationStore(sessionmaker(engine, expire_on_commit=False), clock=lambda: NOW),
        transport,
        EnvironmentSecretResolver({}),
        telemetry(),
        clock=lambda: NOW,
    ).run(lease)

    with Session(engine) as session:
        attempt = session.scalar(
            select(TestAttemptRow)
            .join(ExecutionItemRow)
            .where(ExecutionItemRow.execution_id == execution_id)
        )
        assert attempt is not None
        artifact = session.scalar(
            select(ResponseArtifactRow).where(ResponseArtifactRow.attempt_id == attempt.id)
        )
    assert (
        attempt.state,
        attempt.dispatch_certainty,
        attempt.redirect_rejection_code,
    ) == ("transport_failed", "response_received", "target_denied")
    assert artifact is not None and artifact.headers == {"location": "[REDACTED]"}


def test_concurrent_recovery_creates_exactly_one_successor(
    engine: Engine, seeded_orchestration_catalog: None
) -> None:
    execution_id, jobs = create_execution(engine)
    lease = jobs.claim(uuid4(), 60)
    assert lease is not None
    factory = sessionmaker(engine, expire_on_commit=False)
    store = PostgresOrchestrationStore(factory, clock=lambda: NOW)
    first = store.acquire_next(lease, attempt_id=uuid4())
    assert first is not None
    store.checkpoint_dispatch(
        first.attempt.id,
        lease,
        fingerprint="a" * 64,
        trace_id="b" * 32,
        span_id="c" * 16,
    )
    proposed = [uuid4(), uuid4()]

    def recover(candidate: UUID) -> UUID:
        return (
            PostgresOrchestrationStore(factory, clock=lambda: NOW)
            .schedule_replay(first.attempt.id, lease, successor_id=candidate)
            .id
        )

    with ThreadPoolExecutor(max_workers=2) as workers:
        recovered = list(workers.map(recover, proposed))

    assert recovered[0] == recovered[1]
    with Session(engine) as session:
        attempts = list(
            session.scalars(
                select(TestAttemptRow)
                .join(ExecutionItemRow)
                .where(ExecutionItemRow.execution_id == execution_id)
            )
        )
    assert len(attempts) == 2


def test_evaluation_persistence_rolls_back_before_any_child_or_state_write(
    engine: Engine, seeded_orchestration_catalog: None
) -> None:
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory.begin() as session:
        session.execute(
            update(TestCaseRevisionRow)
            .where(TestCaseRevisionRow.id == CASE_ONE_REVISION_ID)
            .values(
                definition=definition(
                    assertions=[
                        {
                            "id": "00000000-0000-4000-8000-000000000106",
                            "severity": "required",
                            "kind": "status_code",
                            "expected_codes": [200],
                        },
                        {
                            "id": "00000000-0000-4000-8000-000000000107",
                            "severity": "required",
                            "kind": "status_code",
                            "expected_codes": [201],
                        },
                    ]
                )
            )
        )
    execution_id, jobs = create_execution(engine)
    lease = jobs.claim(uuid4(), 60)
    assert lease is not None
    store = PostgresOrchestrationStore(factory, clock=lambda: NOW)
    work = store.acquire_next(lease, attempt_id=uuid4())
    assert work is not None
    store.checkpoint_dispatch(
        work.attempt.id,
        lease,
        fingerprint="a" * 64,
        trace_id="b" * 32,
        span_id="c" * 16,
    )
    store.record_response(
        work.attempt.id,
        lease,
        ResponseArtifact(
            work.attempt.id,
            200,
            {},
            "json",
            {"ok": True},
            11,
            False,
            False,
            NOW,
            NOW + timedelta(days=7),
        ),
        outcome=TransportOutcome.RESPONSE_RECEIVED,
    )
    awaiting = store.acquire_next(lease, attempt_id=uuid4())
    assert awaiting is not None
    result = ExecutionOrchestrator._evaluate(awaiting)
    duplicate_id = uuid4()
    with pytest.raises(IntegrityError):
        store.persist_evaluation(
            awaiting.attempt.id,
            lease,
            result,
            evaluation_ids=(duplicate_id, duplicate_id),
        )

    with Session(engine) as session:
        execution = session.get(ExecutionRow, execution_id)
        item = session.scalar(
            select(ExecutionItemRow).where(ExecutionItemRow.execution_id == execution_id)
        )
        attempt = (
            session.scalar(
                select(TestAttemptRow).where(TestAttemptRow.execution_item_id == item.id)
            )
            if item is not None
            else None
        )
        assert attempt is not None
        assert (
            session.scalar(
                select(func.count(BaselineComparisonRow.attempt_id)).where(
                    BaselineComparisonRow.attempt_id == attempt.id
                )
            )
            == 0
        )
        assert (
            session.scalar(
                select(func.count(EvaluationRow.id)).where(EvaluationRow.attempt_id == attempt.id)
            )
            == 0
        )
    assert execution is not None and execution.status == "running"
    assert item is not None and item.status == "running"
    assert attempt is not None and attempt.state == "response_received"


def test_stale_fence_rejects_evaluation_after_lease_replacement(
    engine: Engine, seeded_orchestration_catalog: None, clock: Clock
) -> None:
    factory = sessionmaker(engine, expire_on_commit=False)
    execution = PostgresExecutionService(factory, clock=clock).create(
        ExecutionCreateCommand(ENVIRONMENT_ID, test_case_id=CASE_ONE_ID)
    )
    jobs = PostgresJobStore(factory, clock=clock)
    old = jobs.claim(uuid4(), 60)
    assert old is not None
    store = PostgresOrchestrationStore(factory, clock=clock)
    work = store.acquire_next(old, attempt_id=uuid4())
    assert work is not None
    store.checkpoint_dispatch(
        work.attempt.id,
        old,
        fingerprint="a" * 64,
        trace_id="b" * 32,
        span_id="c" * 16,
    )
    store.record_response(
        work.attempt.id,
        old,
        ResponseArtifact(
            work.attempt.id,
            200,
            {},
            "json",
            {"ok": True},
            11,
            False,
            False,
            clock.value,
            clock.value + timedelta(days=7),
        ),
        outcome=TransportOutcome.RESPONSE_RECEIVED,
    )
    clock.advance(60)
    replacement = jobs.claim(uuid4(), 60)
    assert replacement is not None
    recovered = store.acquire_next(replacement, attempt_id=uuid4())
    assert recovered is not None
    result = ExecutionOrchestrator._evaluate(recovered)

    with pytest.raises(LeaseLost):
        store.persist_evaluation(
            recovered.attempt.id,
            old,
            result,
            evaluation_ids=tuple(uuid4() for _ in result.evaluations),
        )

    with Session(engine) as session:
        attempt = session.scalar(
            select(TestAttemptRow)
            .join(ExecutionItemRow)
            .where(ExecutionItemRow.execution_id == execution.id)
        )
        assert attempt is not None
        assert attempt.state == "response_received"
        assert (
            session.scalar(
                select(func.count(BaselineComparisonRow.attempt_id)).where(
                    BaselineComparisonRow.attempt_id == attempt.id
                )
            )
            == 0
        )


def test_stale_fence_cannot_commit_after_reclaim(
    engine: Engine, seeded_orchestration_catalog: None, clock: Clock
) -> None:
    factory = sessionmaker(engine, expire_on_commit=False)
    PostgresExecutionService(factory, clock=clock).create(
        ExecutionCreateCommand(ENVIRONMENT_ID, test_case_id=CASE_ONE_ID)
    )
    jobs = PostgresJobStore(factory, clock=clock)
    old = jobs.claim(uuid4(), 60)
    assert old is not None
    store = PostgresOrchestrationStore(factory, clock=clock)
    current = store.acquire_next(old, attempt_id=uuid4())
    assert current is not None
    clock.advance(60)
    assert jobs.claim(uuid4(), 60) is not None

    with pytest.raises(LeaseLost):
        store.checkpoint_dispatch(
            current.attempt.id,
            old,
            fingerprint="a" * 64,
            trace_id="b" * 32,
            span_id="c" * 16,
        )


@pytest.mark.parametrize(
    "checkpoint",
    ["preparation", "response", "outcome", "indeterminate", "recovery", "completion"],
)
def test_mutating_checkpoint_rejects_terminal_execution_without_any_overwrite(
    engine: Engine,
    seeded_orchestration_catalog: None,
    checkpoint: str,
) -> None:
    execution_id, jobs = create_execution(engine)
    lease = jobs.claim(uuid4(), 60)
    assert lease is not None
    factory = sessionmaker(engine, expire_on_commit=False)
    store = PostgresOrchestrationStore(factory, clock=lambda: NOW)
    work = store.acquire_next(lease, attempt_id=uuid4())
    assert work is not None
    needs_dispatch = checkpoint in {"response", "outcome", "indeterminate", "recovery"}
    if needs_dispatch:
        store.checkpoint_dispatch(
            work.attempt.id,
            lease,
            fingerprint="a" * 64,
            trace_id="b" * 32,
            span_id="c" * 16,
        )
    if checkpoint == "recovery":
        PostgresAttemptStore(factory, clock=lambda: NOW).record_transport_failure(
            work.attempt.id,
            lease,
            outcome=TransportOutcome.DNS_FAILURE,
            certainty=DispatchCertainty.NOT_SENT,
            not_sent_proof="dns_failure",
        )
    with factory.begin() as session:
        session.execute(
            update(ExecutionRow)
            .where(ExecutionRow.id == execution_id)
            .values(status="completed", verdict="passed", finished_at=NOW)
        )
        if checkpoint == "completion":
            session.execute(
                update(ExecutionItemRow)
                .where(ExecutionItemRow.execution_id == execution_id)
                .values(status="failed", verdict="not_evaluated", finished_at=NOW)
            )

    def snapshot() -> tuple[object, ...]:
        with Session(engine) as session:
            execution = session.get(ExecutionRow, execution_id)
            item = session.scalar(
                select(ExecutionItemRow).where(ExecutionItemRow.execution_id == execution_id)
            )
            attempt = session.get(TestAttemptRow, work.attempt.id)
            job = session.get(JobRow, lease.job_id)
            artifacts = list(
                session.scalars(
                    select(ResponseArtifactRow).where(
                        ResponseArtifactRow.attempt_id == work.attempt.id
                    )
                )
            )
            assert execution is not None and item is not None and attempt is not None
            assert job is not None
            return (
                execution.status,
                execution.verdict,
                execution.finished_at,
                item.status,
                item.verdict,
                item.finished_at,
                attempt.state,
                attempt.dispatch_certainty,
                attempt.transport_outcome,
                attempt.finished_at,
                job.state,
                job.lease_owner,
                job.lease_token,
                job.finished_at,
                len(artifacts),
            )

    before = snapshot()
    with pytest.raises(OrchestrationConflict, match="execution is not running"):
        if checkpoint == "preparation":
            store.fail_preparation(work.attempt.id, lease, PreparationErrorCode.REQUEST_INVALID)
        elif checkpoint == "response":
            store.record_response(
                work.attempt.id,
                lease,
                ResponseArtifact(
                    work.attempt.id,
                    200,
                    {},
                    "text",
                    "bounded",
                    7,
                    False,
                    False,
                    NOW,
                    NOW + timedelta(days=7),
                ),
                outcome=TransportOutcome.RESPONSE_RECEIVED,
            )
        elif checkpoint == "outcome":
            store.record_transport_failure(
                work.attempt.id,
                lease,
                outcome=TransportOutcome.DNS_FAILURE,
                certainty=DispatchCertainty.NOT_SENT,
                not_sent_proof="dns_failure",
            )
        elif checkpoint == "indeterminate":
            store.mark_indeterminate(work.attempt.id, lease)
        elif checkpoint == "recovery":
            store.resume_terminal(work.attempt.id, lease)
        else:
            store.complete_execution(lease)
    assert snapshot() == before


@pytest.mark.parametrize(
    "checkpoint",
    ["dispatch", "response", "outcome", "replay", "indeterminate", "recovery", "completion"],
)
@pytest.mark.parametrize(
    "fence_failure", ["wrong_owner", "wrong_token", "replaced_token", "expired"]
)
def test_every_checkpoint_rejects_invalid_fence_without_any_overwrite(
    engine: Engine,
    seeded_orchestration_catalog: None,
    clock: Clock,
    checkpoint: str,
    fence_failure: str,
) -> None:
    factory = sessionmaker(engine, expire_on_commit=False)
    execution = PostgresExecutionService(factory, clock=clock).create(
        ExecutionCreateCommand(ENVIRONMENT_ID, test_case_id=CASE_ONE_ID)
    )
    jobs = PostgresJobStore(factory, clock=clock)
    lease = jobs.claim(uuid4(), 60)
    assert lease is not None
    store = PostgresOrchestrationStore(factory, clock=clock)
    work = store.acquire_next(lease, attempt_id=uuid4())
    assert work is not None
    if checkpoint in {"response", "outcome", "replay", "indeterminate", "recovery"}:
        store.checkpoint_dispatch(
            work.attempt.id,
            lease,
            fingerprint="a" * 64,
            trace_id="b" * 32,
            span_id="c" * 16,
        )
    if checkpoint == "recovery":
        PostgresAttemptStore(factory, clock=clock).record_transport_failure(
            work.attempt.id,
            lease,
            outcome=TransportOutcome.DNS_FAILURE,
            certainty=DispatchCertainty.NOT_SENT,
            not_sent_proof="dns_failure",
        )

    invalid = lease
    if fence_failure == "wrong_owner":
        invalid = replace(lease, owner=uuid4())
    elif fence_failure == "wrong_token":
        invalid = replace(lease, token=uuid4())
    elif fence_failure == "replaced_token":
        with factory.begin() as session:
            session.execute(
                update(JobRow).where(JobRow.id == lease.job_id).values(lease_token=uuid4())
            )
    else:
        clock.advance(60)

    def snapshot() -> tuple[object, ...]:
        with Session(engine) as session:
            execution_row = session.get(ExecutionRow, execution.id)
            item = session.scalar(
                select(ExecutionItemRow).where(ExecutionItemRow.execution_id == execution.id)
            )
            attempt = session.get(TestAttemptRow, work.attempt.id)
            job = session.get(JobRow, lease.job_id)
            assert execution_row is not None and item is not None and attempt is not None
            assert job is not None
            return (
                execution_row.status,
                execution_row.verdict,
                execution_row.finished_at,
                item.status,
                item.verdict,
                item.finished_at,
                attempt.state,
                attempt.replay_successor_id,
                attempt.finished_at,
                job.state,
                job.lease_owner,
                job.lease_token,
                job.finished_at,
                session.scalar(select(func.count(TestAttemptRow.id))),
                session.scalar(select(func.count(ResponseArtifactRow.attempt_id))),
            )

    before = snapshot()
    with pytest.raises(LeaseLost):
        if checkpoint == "dispatch":
            store.checkpoint_dispatch(
                work.attempt.id,
                invalid,
                fingerprint="d" * 64,
                trace_id="e" * 32,
                span_id="f" * 16,
            )
        elif checkpoint == "response":
            store.record_response(
                work.attempt.id,
                invalid,
                ResponseArtifact(
                    work.attempt.id,
                    200,
                    {},
                    "text",
                    "bounded",
                    7,
                    False,
                    False,
                    clock.value,
                    clock.value + timedelta(days=7),
                ),
                outcome=TransportOutcome.RESPONSE_RECEIVED,
            )
        elif checkpoint == "outcome":
            store.record_transport_failure(
                work.attempt.id,
                invalid,
                outcome=TransportOutcome.DNS_FAILURE,
                certainty=DispatchCertainty.NOT_SENT,
                not_sent_proof="dns_failure",
            )
        elif checkpoint == "replay":
            store.schedule_replay(work.attempt.id, invalid, successor_id=uuid4())
        elif checkpoint == "indeterminate":
            store.mark_indeterminate(work.attempt.id, invalid)
        elif checkpoint == "recovery":
            store.resume_terminal(work.attempt.id, invalid)
        else:
            store.complete_execution(invalid)
    assert snapshot() == before


@pytest.mark.parametrize(
    "fence_failure", ["wrong_owner", "wrong_token", "replaced_token", "expired"]
)
def test_acquire_next_rejects_each_invalid_fence_using_postgresql_time(
    engine: Engine,
    seeded_orchestration_catalog: None,
    fence_failure: str,
) -> None:
    factory = sessionmaker(engine, expire_on_commit=False)
    execution = PostgresExecutionService(factory).create(
        ExecutionCreateCommand(ENVIRONMENT_ID, test_case_id=CASE_ONE_ID)
    )
    lease = PostgresJobStore(factory).claim(uuid4(), 60)
    assert lease is not None
    invalid = lease
    if fence_failure == "wrong_owner":
        invalid = replace(lease, owner=uuid4())
    elif fence_failure == "wrong_token":
        invalid = replace(lease, token=uuid4())
    elif fence_failure == "replaced_token":
        with factory.begin() as session:
            session.execute(
                update(JobRow).where(JobRow.id == lease.job_id).values(lease_token=uuid4())
            )
    else:
        with factory.begin() as session:
            session.execute(
                update(JobRow)
                .where(JobRow.id == lease.job_id)
                .values(lease_expires_at=text("clock_timestamp() - interval '1 second'"))
            )
            is_expired = session.scalar(
                select(JobRow.lease_expires_at < func.clock_timestamp()).where(
                    JobRow.id == lease.job_id
                )
            )
        assert is_expired is True

    proposed_attempt_id = uuid4()
    with pytest.raises(LeaseLost):
        PostgresOrchestrationStore(factory).acquire_next(invalid, attempt_id=proposed_attempt_id)

    with Session(engine) as session:
        execution_row = session.get(ExecutionRow, execution.id)
        item = session.scalar(
            select(ExecutionItemRow).where(ExecutionItemRow.execution_id == execution.id)
        )
        attempt = session.get(TestAttemptRow, proposed_attempt_id)
        job = session.get(JobRow, lease.job_id)
    assert execution_row is not None and execution_row.status == "queued"
    assert item is not None and (item.status, item.started_at) == ("pending", None)
    assert attempt is None
    assert job is not None and job.state == "leased"


@pytest.mark.parametrize(
    "fence_failure", ["wrong_owner", "wrong_token", "replaced_token", "expired"]
)
def test_fail_preparation_rejects_each_invalid_fence_using_postgresql_time(
    engine: Engine,
    seeded_orchestration_catalog: None,
    fence_failure: str,
) -> None:
    factory = sessionmaker(engine, expire_on_commit=False)
    execution = PostgresExecutionService(factory).create(
        ExecutionCreateCommand(ENVIRONMENT_ID, test_case_id=CASE_ONE_ID)
    )
    lease = PostgresJobStore(factory).claim(uuid4(), 60)
    assert lease is not None
    store = PostgresOrchestrationStore(factory)
    work = store.acquire_next(lease, attempt_id=uuid4())
    assert work is not None
    invalid = lease
    if fence_failure == "wrong_owner":
        invalid = replace(lease, owner=uuid4())
    elif fence_failure == "wrong_token":
        invalid = replace(lease, token=uuid4())
    elif fence_failure == "replaced_token":
        with factory.begin() as session:
            session.execute(
                update(JobRow).where(JobRow.id == lease.job_id).values(lease_token=uuid4())
            )
    else:
        with factory.begin() as session:
            session.execute(
                update(JobRow)
                .where(JobRow.id == lease.job_id)
                .values(lease_expires_at=text("clock_timestamp() - interval '1 second'"))
            )
            is_expired = session.scalar(
                select(JobRow.lease_expires_at < func.clock_timestamp()).where(
                    JobRow.id == lease.job_id
                )
            )
        assert is_expired is True

    with pytest.raises(LeaseLost):
        store.fail_preparation(work.attempt.id, invalid, PreparationErrorCode.REQUEST_INVALID)

    with Session(engine) as session:
        execution_row = session.get(ExecutionRow, execution.id)
        item = session.scalar(
            select(ExecutionItemRow).where(ExecutionItemRow.execution_id == execution.id)
        )
        attempt = session.get(TestAttemptRow, work.attempt.id)
        job = session.get(JobRow, lease.job_id)
    assert execution_row is not None and (
        execution_row.status,
        execution_row.finished_at,
    ) == ("running", None)
    assert item is not None and (item.status, item.finished_at) == ("running", None)
    assert attempt is not None and (
        attempt.state,
        attempt.preparation_error_code,
        attempt.finished_at,
    ) == ("prepared", None, None)
    assert job is not None and job.state == "leased"


def test_orchestration_uses_postgresql_clock_when_no_test_clock_is_injected(
    engine: Engine, seeded_orchestration_catalog: None
) -> None:
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as session:
        before = session.scalar(select(func.clock_timestamp()))
    assert isinstance(before, datetime)
    execution = PostgresExecutionService(factory).create(
        ExecutionCreateCommand(ENVIRONMENT_ID, test_case_id=CASE_ONE_ID)
    )
    lease = PostgresJobStore(factory).claim(uuid4(), 60)
    assert lease is not None

    work = PostgresOrchestrationStore(factory).acquire_next(lease, attempt_id=uuid4())

    with factory() as session:
        after = session.scalar(select(func.clock_timestamp()))
    assert work is not None and isinstance(after, datetime)
    assert before <= work.attempt.created_at <= after
    with Session(engine) as session:
        execution_row = session.get(ExecutionRow, execution.id)
    assert execution_row is not None and isinstance(execution_row.started_at, datetime)
    assert before <= execution_row.started_at <= after


@pytest.mark.parametrize("method", ["HEAD", "OPTIONS"])
def test_safe_method_recovery_replays_head_and_options_with_a_fresh_attempt(
    engine: Engine,
    seeded_orchestration_catalog: None,
    clock: Clock,
    method: str,
) -> None:
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory.begin() as session:
        session.execute(
            update(TestCaseRevisionRow)
            .where(TestCaseRevisionRow.id == CASE_ONE_REVISION_ID)
            .values(definition=definition(method, "/one"))
        )
    execution = PostgresExecutionService(factory, clock=clock).create(
        ExecutionCreateCommand(ENVIRONMENT_ID, test_case_id=CASE_ONE_ID)
    )
    jobs = PostgresJobStore(factory, clock=clock)
    lease = jobs.claim(uuid4(), 60)
    assert lease is not None
    store = PostgresOrchestrationStore(factory, clock=clock)
    first = store.acquire_next(lease, attempt_id=uuid4())
    assert first is not None
    store.checkpoint_dispatch(
        first.attempt.id,
        lease,
        fingerprint="a" * 64,
        trace_id="b" * 32,
        span_id="c" * 16,
    )
    clock.advance(60)
    recovered = jobs.claim(uuid4(), 60)
    assert recovered is not None
    transport = ScriptedTransport(iter([response("replayed", kind="text")]))

    ExecutionOrchestrator(
        store,
        transport,
        EnvironmentSecretResolver({}),
        telemetry(),
        clock=clock,
    ).run(recovered)

    assert [request.method for request in transport.requests] == [method]
    with Session(engine) as session:
        attempts = list(
            session.scalars(
                select(TestAttemptRow)
                .join(ExecutionItemRow)
                .where(ExecutionItemRow.execution_id == execution.id)
                .order_by(TestAttemptRow.sequence)
            )
        )
    assert [attempt.state for attempt in attempts] == [
        "replay_scheduled",
        "evaluated",
    ]
    assert attempts[0].replay_successor_id == attempts[1].id
    assert attempts[0].primary_trace_id != attempts[1].primary_trace_id
    assert attempts[0].client_span_id != attempts[1].client_span_id


def test_response_persistence_failure_rolls_back_attempt_item_and_job(
    engine: Engine, seeded_orchestration_catalog: None
) -> None:
    execution_id, jobs = create_execution(engine)
    lease = jobs.claim(uuid4(), 60)
    assert lease is not None
    store = PostgresOrchestrationStore(
        sessionmaker(engine, expire_on_commit=False), clock=lambda: NOW
    )
    work = store.acquire_next(lease, attempt_id=uuid4())
    assert work is not None
    store.checkpoint_dispatch(
        work.attempt.id,
        lease,
        fingerprint="a" * 64,
        trace_id="b" * 32,
        span_id="c" * 16,
    )

    with pytest.raises(DefinitionValidationError):
        store.record_response(
            work.attempt.id,
            lease,
            ResponseArtifact(
                work.attempt.id,
                200,
                {},
                "json",
                object(),
                1,
                False,
                False,
                NOW,
                NOW + timedelta(days=7),
            ),
            outcome=TransportOutcome.RESPONSE_RECEIVED,
        )

    with Session(engine) as session:
        attempt = session.get(TestAttemptRow, work.attempt.id)
        item = session.scalar(
            select(ExecutionItemRow).where(ExecutionItemRow.execution_id == execution_id)
        )
        job = session.get(JobRow, lease.job_id)
        artifact = session.get(ResponseArtifactRow, work.attempt.id)
    assert attempt is not None and attempt.state == "dispatching"
    assert item is not None and item.status == "running"
    assert job is not None and job.state == "leased"
    assert artifact is None


def test_resolved_secret_exists_only_in_memory_not_durable_results_or_logs(
    engine: Engine,
    seeded_orchestration_catalog: None,
    caplog: pytest.LogCaptureFixture,
) -> None:
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory.begin() as session:
        session.execute(
            update(EnvironmentRevisionRow)
            .where(EnvironmentRevisionRow.id == ENVIRONMENT_REVISION_ID)
            .values(
                definition={
                    "schema_version": 1,
                    "base_url": "https://api.example.test/",
                    "variables": {},
                    "secret_references": [{"$secret": "API_TOKEN"}],
                    "target_policy": {},
                }
            )
        )
        session.execute(
            update(TestCaseRevisionRow)
            .where(TestCaseRevisionRow.id == CASE_ONE_REVISION_ID)
            .values(
                definition={
                    "schema_version": 1,
                    "request": {
                        "method": "GET",
                        "path": "/one",
                        "headers": [{"name": "Authorization", "value": {"$secret": "API_TOKEN"}}],
                    },
                }
            )
        )
    _execution_id, jobs = create_execution(engine)
    lease = jobs.claim(uuid4(), 60)
    assert lease is not None
    transport = ScriptedTransport(iter([response("safe", kind="text")]))

    ExecutionOrchestrator(
        PostgresOrchestrationStore(factory, clock=lambda: NOW),
        transport,
        EnvironmentSecretResolver({"SENTINEL_SECRET_API_TOKEN": "synthetic-canary"}),
        telemetry(),
        clock=lambda: NOW,
    ).run(lease)

    assert transport.requests[0].headers["authorization"] == "synthetic-canary"
    with engine.connect() as connection:
        durable_result_text = "\n".join(
            str(value)
            for statement in (
                "SELECT to_jsonb(t)::text FROM test_attempts AS t",
                "SELECT to_jsonb(r)::text FROM response_artifacts AS r",
                "SELECT to_jsonb(j)::text FROM jobs AS j",
            )
            for value in connection.scalars(text(statement))
        )
    assert "synthetic-canary" not in durable_result_text
    assert "synthetic-canary" not in caplog.text

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from sentinel.catalog.changes import ChangeEvent
from sentinel.persistence.models import (
    BaselineActivationRow,
    BaselineComparisonRow,
    BaselineRow,
    ChangeEventRow,
    EnvironmentRevisionRow,
    EnvironmentRow,
    EvaluationRow,
    ExecutionItemRow,
    ExecutionRow,
    ProjectRow,
    TestAttemptRow,
    TestCaseRevisionRow,
    TestCaseRow,
)
from sentinel.persistence.regression import PostgresBaselineUnitOfWork
from sentinel.regression.baselines import (
    BaselineIneligible,
    BaselineNotFound,
    BaselineResourceConflict,
    BaselineRevisionConflict,
    BaselineScope,
    BaselineService,
    ScopeState,
    make_scope_etag,
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
            "rule": "000000000009",
            "baseline": "00000000000a",
        }.items()
    }


def _seed_evaluable_scope(
    factory: sessionmaker[Session], *, seed: int = 72000000
) -> dict[str, UUID]:
    ids = _ids(seed)
    definition = {
        "comparison_policy": {"selectors": [{"id": str(ids["rule"]), "pointer": "/value"}]}
    }
    with factory.begin() as session:
        session.add(
            ProjectRow(
                id=ids["project"],
                name=f"m4-baseline-{seed}",
                state_version=1,
                created_at=NOW,
            )
        )
        session.flush()
        session.add(
            EnvironmentRow(
                id=ids["environment"],
                project_id=ids["project"],
                name="env",
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
                name="case",
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
                definition=definition,
                policy_fingerprint="a" * 64,
                created_at=NOW,
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
                status="completed",
                verdict="baseline_required",
                result_contract_version=1,
                created_at=NOW,
                finished_at=NOW,
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
                baseline_activation_id=None,
                baseline_id=None,
                status="completed",
                verdict="baseline_required",
                started_at=NOW,
                finished_at=NOW,
            )
        )
        session.add(
            TestAttemptRow(
                id=ids["attempt"],
                execution_item_id=ids["item"],
                sequence=1,
                result_contract_version=1,
                state="evaluated",
                dispatch_certainty="response_received",
                request_fingerprint="c" * 64,
                created_at=NOW,
                dispatch_recorded_at=NOW,
                response_recorded_at=NOW,
                finished_at=NOW,
                transport_outcome="response_received",
                primary_trace_id="d" * 32,
                client_span_id="e" * 16,
                included_in_verdict=True,
                verdict="baseline_required",
            )
        )
        session.flush()
        session.add(
            BaselineComparisonRow(
                attempt_id=ids["attempt"],
                state="missing",
                baseline_activation_id=None,
                baseline_id=None,
                baseline_version=None,
                policy_fingerprint=None,
                checked_at=NOW,
            )
        )
        session.add(
            EvaluationRow(
                id=uuid4(),
                attempt_id=ids["attempt"],
                ordinal=0,
                kind="baseline_selector",
                rule_id=ids["rule"],
                severity="required",
                outcome="not_evaluated",
                message_code="baseline_missing",
                expected=None,
                actual="stable",
                evidence_omitted=False,
                created_at=NOW,
            )
        )
    return ids


def _service(factory: sessionmaker[Session], ids: dict[str, UUID]) -> BaselineService:
    return BaselineService(
        lambda: PostgresBaselineUnitOfWork(factory), ids=uuid4, clock=lambda: NOW
    )


def _add_source(factory: sessionmaker[Session], ids: dict[str, UUID], *, seed: int) -> UUID:
    source = _ids(seed)
    with factory.begin() as session:
        session.add(
            ExecutionRow(
                id=source["execution"],
                project_id=ids["project"],
                environment_id=ids["environment"],
                environment_revision_id=ids["environment_revision"],
                source_type="test_case",
                source_id=ids["test_case"],
                source_revision_id=ids["test_case_revision"],
                status="completed",
                verdict="baseline_required",
                result_contract_version=1,
                created_at=NOW,
                finished_at=NOW,
            )
        )
        session.flush()
        session.add(
            ExecutionItemRow(
                id=source["item"],
                execution_id=source["execution"],
                ordinal=0,
                project_id=ids["project"],
                test_case_id=ids["test_case"],
                test_case_revision_id=ids["test_case_revision"],
                test_case_revision_version=1,
                result_contract_version=1,
                baseline_activation_id=None,
                baseline_id=None,
                status="completed",
                verdict="baseline_required",
                started_at=NOW,
                finished_at=NOW,
            )
        )
        session.flush()
        session.add(
            TestAttemptRow(
                id=source["attempt"],
                execution_item_id=source["item"],
                sequence=1,
                result_contract_version=1,
                state="evaluated",
                dispatch_certainty="response_received",
                request_fingerprint="f" * 64,
                created_at=NOW,
                dispatch_recorded_at=NOW,
                response_recorded_at=NOW,
                finished_at=NOW,
                transport_outcome="response_received",
                primary_trace_id="1" * 32,
                client_span_id="2" * 16,
                included_in_verdict=True,
                verdict="baseline_required",
            )
        )
        session.flush()
        session.add(
            BaselineComparisonRow(
                attempt_id=source["attempt"],
                state="missing",
                baseline_activation_id=None,
                baseline_id=None,
                baseline_version=None,
                policy_fingerprint=None,
                checked_at=NOW,
            )
        )
        session.add(
            EvaluationRow(
                id=uuid4(),
                attempt_id=source["attempt"],
                ordinal=0,
                kind="baseline_selector",
                rule_id=ids["rule"],
                severity="required",
                outcome="not_evaluated",
                message_code="baseline_missing",
                expected=None,
                actual="replacement",
                evidence_omitted=False,
                created_at=NOW,
            )
        )
    return source["attempt"]


def test_promotion_activation_history_and_retry_are_atomic(engine: Engine) -> None:
    factory = sessionmaker(engine, expire_on_commit=False)
    ids = _seed_evaluable_scope(factory)
    scope = BaselineScope(ids["test_case"], ids["environment"])
    service = _service(factory, ids)
    initial_etag = make_scope_etag(scope, ScopeState(0, None))

    created = service.promote(
        scope,
        source_attempt_id=ids["attempt"],
        reason="bootstrap",
        confirmation="promote_selected_values",
        acknowledged_warnings=["missing_baseline"],
        if_match=initial_etag,
    )

    assert created.created
    assert created.activation.reason is None
    assert created.baseline.reason == "bootstrap"
    assert created.baseline.active

    retry = service.promote(
        scope,
        source_attempt_id=ids["attempt"],
        reason="bootstrap",
        confirmation="promote_selected_values",
        acknowledged_warnings=["missing_baseline"],
        if_match=initial_etag,
    )
    assert not retry.created
    assert retry.baseline.id == created.baseline.id
    assert retry.activation.id == created.activation.id

    with pytest.raises(BaselineResourceConflict):
        service.promote(
            scope,
            source_attempt_id=ids["attempt"],
            reason="bootstrap",
            confirmation="wrong_confirmation",
            acknowledged_warnings=["missing_baseline"],
            if_match=initial_etag,
        )
    with pytest.raises(BaselineResourceConflict):
        service.promote(
            scope,
            source_attempt_id=ids["attempt"],
            reason="bootstrap",
            confirmation="promote_selected_values",
            acknowledged_warnings=[],
            if_match=initial_etag,
        )

    with Session(engine) as session:
        assert session.scalar(select(BaselineRow.version)) == 1
        assert session.scalar(select(BaselineActivationRow.baseline_id)) == created.baseline.id
        event = session.scalar(select(ChangeEventRow))
        assert event is not None
        assert event.summary == {"changed_fields": ["baseline_activation"]}
        assert event.before_ref is None
        assert event.after_ref == created.activation.id


def test_wrong_scope_and_stale_precondition_do_not_mutate(engine: Engine) -> None:
    factory = sessionmaker(engine, expire_on_commit=False)
    ids = _seed_evaluable_scope(factory, seed=72000001)
    scope = BaselineScope(ids["test_case"], ids["environment"])
    service = _service(factory, ids)
    with pytest.raises(BaselineRevisionConflict):
        service.promote(
            scope,
            source_attempt_id=ids["attempt"],
            reason=None,
            confirmation="promote_selected_values",
            acknowledged_warnings=["missing_baseline"],
            if_match=make_scope_etag(scope, ScopeState(3, None)),
        )

    other = _seed_evaluable_scope(factory, seed=72000002)
    with pytest.raises(BaselineNotFound):
        service.promote(
            scope,
            source_attempt_id=other["attempt"],
            reason=None,
            confirmation="promote_selected_values",
            acknowledged_warnings=["missing_baseline"],
            if_match=make_scope_etag(scope, ScopeState(0, None)),
        )
    with Session(engine) as session:
        assert session.scalar(select(BaselineRow.id)) is None


def test_ineligible_source_and_scope_history_are_safe(engine: Engine) -> None:
    factory = sessionmaker(engine, expire_on_commit=False)
    ids = _seed_evaluable_scope(factory, seed=72000003)
    with factory.begin() as session:
        attempt = session.get(TestAttemptRow, ids["attempt"])
        assert attempt is not None
        attempt.included_in_verdict = False
    scope = BaselineScope(ids["test_case"], ids["environment"])
    service = _service(factory, ids)
    with pytest.raises(BaselineIneligible):
        service.promote(
            scope,
            source_attempt_id=ids["attempt"],
            reason=None,
            confirmation="promote_selected_values",
            acknowledged_warnings=["missing_baseline"],
            if_match=make_scope_etag(scope, ScopeState(0, None)),
        )
    page = service.list_history(scope, after=None, limit=100)
    assert page.items == ()


@pytest.mark.parametrize(
    ("message_code", "actual", "evidence_omitted", "expected_code", "seed"),
    [
        ("content_redacted", None, True, "selected_value_unavailable", 72000009),
        ("baseline_missing", None, True, "selected_value_too_large", 72000010),
        ("baseline_missing", "[REDACTED]", False, "selected_value_unavailable", 72000011),
    ],
)
def test_redacted_and_oversized_values_cannot_be_promoted(
    engine: Engine,
    message_code: str,
    actual: object,
    evidence_omitted: bool,
    expected_code: str,
    seed: int,
) -> None:
    factory = sessionmaker(engine, expire_on_commit=False)
    ids = _seed_evaluable_scope(factory, seed=seed)
    with factory.begin() as session:
        evaluation = session.scalar(
            select(EvaluationRow).where(EvaluationRow.attempt_id == ids["attempt"])
        )
        assert evaluation is not None
        evaluation.message_code = message_code
        evaluation.actual = actual
        evaluation.evidence_omitted = evidence_omitted
    scope = BaselineScope(ids["test_case"], ids["environment"])
    with pytest.raises(BaselineIneligible) as error:
        _service(factory, ids).promote(
            scope,
            source_attempt_id=ids["attempt"],
            reason=None,
            confirmation="promote_selected_values",
            acknowledged_warnings=["missing_baseline"],
            if_match=make_scope_etag(scope, ScopeState(0, None)),
        )
    assert error.value.codes == (expected_code,)


def test_activation_rollback_pagination_and_transaction_rollback(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    factory = sessionmaker(engine, expire_on_commit=False)
    ids = _seed_evaluable_scope(factory, seed=72000004)
    scope = BaselineScope(ids["test_case"], ids["environment"])
    service = _service(factory, ids)
    first = service.promote(
        scope,
        source_attempt_id=ids["attempt"],
        reason=None,
        confirmation="promote_selected_values",
        acknowledged_warnings=["missing_baseline"],
        if_match=make_scope_etag(scope, ScopeState(0, None)),
    )
    second_source = _add_source(factory, ids, seed=72000005)

    with Session(engine) as session:
        second_baseline = BaselineRow(
            id=uuid4(),
            test_case_id=ids["test_case"],
            environment_id=ids["environment"],
            project_id=ids["project"],
            version=2,
            source_attempt_id=second_source,
            source_execution_id=uuid4(),
            source_test_case_revision_id=ids["test_case_revision"],
            source_attempt_verdict="baseline_required",
            source_finished_at=NOW,
            policy_fingerprint="a" * 64,
            selected_values_schema_version=1,
            selected_values={"schema_version": 1, "values": []},
            reason="second",
            created_at=NOW,
        )
        second_baseline_id = second_baseline.id
        session.add(second_baseline)
        session.commit()

    activated = service.activate(
        scope,
        baseline_id=second_baseline_id,
        reason="rollback reason",
        if_match=make_scope_etag(scope, ScopeState(2, first.activation.id)),
    )
    assert activated.created
    assert activated.activation.reason == "rollback reason"
    again = service.activate(
        scope,
        baseline_id=second_baseline_id,
        reason="ignored",
        if_match=activated.etag,
    )
    assert not again.created
    assert again.activation.reason == "rollback reason"

    page = service.list_history(scope, after=None, limit=1)
    assert [item.version for item in page.items] == [1]
    assert page.next_after == (1, first.baseline.id)
    assert page.items[0].active is False

    original_add_change = PostgresBaselineUnitOfWork.add_change

    def fail_add_change(self: PostgresBaselineUnitOfWork, event: ChangeEvent) -> None:
        raise RuntimeError("injected change-event failure")

    monkeypatch.setattr(PostgresBaselineUnitOfWork, "add_change", fail_add_change)
    third_source = _add_source(factory, ids, seed=72000006)
    with pytest.raises(RuntimeError):
        service.promote(
            scope,
            source_attempt_id=third_source,
            reason=None,
            confirmation="promote_selected_values",
            acknowledged_warnings=["missing_baseline"],
            if_match=activated.etag,
        )
    monkeypatch.setattr(PostgresBaselineUnitOfWork, "add_change", original_add_change)
    with Session(engine) as session:
        assert (
            session.scalar(
                select(BaselineRow.source_attempt_id).where(
                    BaselineRow.source_attempt_id == third_source
                )
            )
            is None
        )
        current = session.scalar(
            select(BaselineActivationRow).where(
                BaselineActivationRow.deactivated_at.is_(None),
                BaselineActivationRow.test_case_id == ids["test_case"],
                BaselineActivationRow.environment_id == ids["environment"],
            )
        )
        assert current is not None
        assert current.baseline_id == second_baseline_id


def test_concurrent_promotions_share_one_scope_lock(engine: Engine) -> None:
    factory = sessionmaker(engine, expire_on_commit=False)
    ids = _seed_evaluable_scope(factory, seed=72000007)
    second_source = _add_source(factory, ids, seed=72000008)
    scope = BaselineScope(ids["test_case"], ids["environment"])
    etag = make_scope_etag(scope, ScopeState(0, None))

    def promote(source_attempt_id: UUID) -> str:
        try:
            _service(factory, ids).promote(
                scope,
                source_attempt_id=source_attempt_id,
                reason=None,
                confirmation="promote_selected_values",
                acknowledged_warnings=["missing_baseline"],
                if_match=etag,
            )
        except BaselineRevisionConflict:
            return "stale"
        return "created"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(promote, [ids["attempt"], second_source]))
    assert sorted(results) == ["created", "stale"]
    with Session(engine) as session:
        assert session.scalar(select(BaselineRow.version).order_by(BaselineRow.version.desc())) == 1
        assert session.scalar(select(BaselineActivationRow.deactivated_at)) is None
        assert (
            session.scalar(
                select(ChangeEventRow.id).where(ChangeEventRow.kind == "baseline_activated")
            )
            is not None
        )

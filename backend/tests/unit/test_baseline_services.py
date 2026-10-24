from dataclasses import replace
from datetime import UTC, datetime
from hashlib import sha256
from types import TracebackType
from uuid import UUID, uuid4

import pytest

from sentinel.catalog.changes import ChangeEvent
from sentinel.regression.baselines import (
    ActivationSummary,
    BaselineConfirmationRequired,
    BaselineCreateResult,
    BaselineScope,
    BaselineService,
    BaselineSummary,
    ScopeETagError,
    ScopeState,
    SourceAssessment,
    make_scope_etag,
    parse_scope_etag,
)

NOW = datetime(2030, 1, 1, tzinfo=UTC)


class _Repository:
    def __init__(self, scope: BaselineScope, current: ActivationSummary | None = None) -> None:
        self.scope = scope
        self.state = ScopeState(1 if current else 0, current.id if current else None)
        self.current = current
        self.baseline: BaselineSummary | None = None
        self.assessment = SourceAssessment(
            source_attempt_id=uuid4(),
            source_execution_id=uuid4(),
            source_test_case_revision_id=uuid4(),
            project_id=uuid4(),
            source_attempt_verdict="baseline_required",
            source_finished_at=NOW,
            policy_fingerprint="a" * 64,
            selected_values={"schema_version": 1, "values": []},
            warning_codes=("missing_baseline",),
            ineligibility_codes=(),
        )
        self.closed: list[UUID] = []

    def get_scope(self, scope: BaselineScope, *, for_update: bool = False) -> ScopeState:
        assert scope == self.scope
        return self.state

    def current_policy_fingerprint(self, scope: BaselineScope) -> str:
        assert scope == self.scope
        return "a" * 64

    def current_activation(self, scope: BaselineScope) -> ActivationSummary | None:
        return self.current

    def get_by_source_attempt(self, source_attempt_id: UUID) -> BaselineSummary | None:
        return None

    def get_initial_activation(self, baseline_id: UUID) -> ActivationSummary | None:
        return None

    def get(self, scope: BaselineScope, baseline_id: UUID) -> BaselineSummary | None:
        return None

    def get_source_assessment(
        self, scope: BaselineScope, source_attempt_id: UUID, *, current_policy_fingerprint: str
    ) -> SourceAssessment:
        return self.assessment

    def list(
        self,
        scope: BaselineScope,
        *,
        after: tuple[int, UUID] | None,
        limit: int,
    ) -> list[BaselineSummary]:
        return []

    def add_baseline(self, value: BaselineSummary, *, selected_values: dict[str, object]) -> None:
        self.baseline = value

    def add_activation(self, value: ActivationSummary) -> None:
        self.current = value
        self.state = ScopeState(value.baseline_version, value.id)

    def close_current_activation(self, activation_id: UUID, *, at: datetime) -> None:
        self.closed.append(activation_id)
        if self.current is not None and self.current.id == activation_id:
            self.current = replace(self.current, deactivated_at=at)


class _Unit:
    def __init__(self, repository: _Repository) -> None:
        from sentinel.regression.ports import BaselineRepository

        self.baselines: BaselineRepository = repository
        self.events: list[ChangeEvent] = []
        self.commits = 0

    def __enter__(self) -> "_Unit":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None

    def add_change(self, event: ChangeEvent) -> None:
        self.events.append(event)

    def commit(self) -> None:
        self.commits += 1


def test_scope_etag_is_strong_quoted_and_round_trips_canonical_state() -> None:
    scope = BaselineScope(
        test_case_id=UUID("00000000-0000-4000-8000-000000000001"),
        environment_id=UUID("00000000-0000-4000-8000-000000000002"),
    )
    state = ScopeState(latest_version=3, current_activation_id=None)

    token = make_scope_etag(scope, state)

    assert token.startswith('"baseline-scope:')
    assert token.endswith('"')
    digest = sha256(b'{"current_activation_id":null,"latest_version":3}').hexdigest()
    assert token == f'"baseline-scope:{scope.test_case_id}:{scope.environment_id}:{digest}"'
    parsed = parse_scope_etag(token, scope)
    assert parsed.scope == scope
    assert len(parsed.digest) == 64


def test_scope_etag_rejects_weak_or_wrong_scope_tokens() -> None:
    scope = BaselineScope(
        test_case_id=UUID("00000000-0000-4000-8000-000000000001"),
        environment_id=UUID("00000000-0000-4000-8000-000000000002"),
    )
    other_scope = BaselineScope(
        test_case_id=scope.test_case_id,
        environment_id=UUID("00000000-0000-4000-8000-000000000003"),
    )
    token = make_scope_etag(scope, ScopeState(latest_version=1, current_activation_id=None))

    with pytest.raises(ScopeETagError):
        parse_scope_etag(f"W/{token}", scope)
    with pytest.raises(ScopeETagError):
        parse_scope_etag(token, other_scope)


def test_promotion_replacement_closes_current_and_emits_safe_event() -> None:
    scope = BaselineScope(
        UUID("00000000-0000-4000-8000-000000000001"),
        UUID("00000000-0000-4000-8000-000000000002"),
    )
    current = ActivationSummary(
        uuid4(), scope.test_case_id, scope.environment_id, uuid4(), uuid4(), 1, NOW, None, None
    )
    repository = _Repository(scope, current)
    unit = _Unit(repository)
    ids = iter([uuid4(), uuid4(), uuid4()])
    service = BaselineService(lambda: unit, ids=lambda: next(ids), clock=lambda: NOW)

    result = service.promote(
        scope,
        source_attempt_id=repository.assessment.source_attempt_id,
        reason=None,
        confirmation="promote_selected_values",
        acknowledged_warnings=["missing_baseline"],
        if_match=make_scope_etag(scope, repository.state),
    )

    assert isinstance(result, BaselineCreateResult)
    assert repository.closed == [current.id]
    assert result.activation.reason is None
    assert result.created
    assert len(unit.events) == 1
    assert isinstance(unit.events[0], ChangeEvent)
    assert unit.events[0].before_ref == current.id


def test_promotion_requires_exact_sorted_warning_acknowledgement() -> None:
    scope = BaselineScope(
        UUID("00000000-0000-4000-8000-000000000011"),
        UUID("00000000-0000-4000-8000-000000000012"),
    )
    repository = _Repository(scope)
    repository.assessment = replace(
        repository.assessment,
        warning_codes=("missing_baseline", "observed_change"),
    )
    unit = _Unit(repository)
    service = BaselineService(lambda: unit, ids=uuid4, clock=lambda: NOW)

    with pytest.raises(BaselineConfirmationRequired):
        service.promote(
            scope,
            source_attempt_id=repository.assessment.source_attempt_id,
            reason=None,
            confirmation="promote_selected_values",
            acknowledged_warnings=["observed_change", "missing_baseline"],
            if_match=make_scope_etag(scope, repository.state),
        )
    assert unit.commits == 0

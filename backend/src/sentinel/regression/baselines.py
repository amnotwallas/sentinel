"""Pure application decisions for immutable baseline promotion and activation."""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from typing import TYPE_CHECKING, Final
from uuid import UUID

from sentinel.persistence.regression import PersistenceValidationError, validate_reason
from sentinel.regression.policy import canonical_json

if TYPE_CHECKING:
    from sentinel.catalog.changes import ChangeEvent
    from sentinel.regression.ports import BaselineUnitOfWork

_ETAG = re.compile(r'^"baseline-scope:([0-9a-f-]{36}):([0-9a-f-]{36}):([0-9a-f]{64})"$')
_CONFIRMATION: Final = "promote_selected_values"
_WARNING_ORDER: Final = (
    "missing_baseline",
    "incompatible_baseline",
    "observed_change",
    "performance_warning",
)


@dataclass(frozen=True, slots=True)
class BaselineScope:
    test_case_id: UUID
    environment_id: UUID


@dataclass(frozen=True, slots=True)
class ScopeState:
    latest_version: int
    current_activation_id: UUID | None


@dataclass(frozen=True, slots=True)
class ParsedScopeETag:
    scope: BaselineScope
    digest: str


def _scope_digest(state: ScopeState) -> str:
    return sha256(
        canonical_json(
            {
                "latest_version": state.latest_version,
                "current_activation_id": (
                    str(state.current_activation_id) if state.current_activation_id else None
                ),
            }
        ).encode("utf-8")
    ).hexdigest()


def make_scope_etag(scope: BaselineScope, state: ScopeState) -> str:
    if state.latest_version < 0:
        raise ValueError("latest version cannot be negative")
    return f'"baseline-scope:{scope.test_case_id}:{scope.environment_id}:{_scope_digest(state)}"'


class ScopeETagError(ValueError):
    """The token is not one strong, scope-bound baseline ETag."""


def parse_scope_etag(value: str, scope: BaselineScope) -> ParsedScopeETag:
    match = _ETAG.fullmatch(value)
    if match is None:
        raise ScopeETagError
    parsed_scope = BaselineScope(UUID(match.group(1)), UUID(match.group(2)))
    if parsed_scope != scope:
        raise ScopeETagError
    return ParsedScopeETag(parsed_scope, match.group(3))


class BaselineError(Exception):
    code = "baseline_error"


class BaselineNotFound(BaselineError):
    code = "resource_not_found"


class BaselineValidationError(BaselineError, ValueError):
    code = "validation_failed"


class BaselineRevisionConflict(BaselineError):
    code = "revision_conflict"


class BaselineIneligible(BaselineError):
    code = "baseline_ineligible"

    def __init__(self, codes: tuple[str, ...]) -> None:
        self.codes = codes
        super().__init__()


class BaselineIncompatible(BaselineError):
    code = "baseline_incompatible"


class BaselineConfirmationRequired(BaselineError):
    code = "baseline_confirmation_required"


class BaselineResourceConflict(BaselineError):
    code = "resource_conflict"


@dataclass(frozen=True, slots=True)
class BaselineSummary:
    id: UUID
    test_case_id: UUID
    environment_id: UUID
    project_id: UUID
    version: int
    source_attempt_id: UUID
    source_execution_id: UUID
    source_test_case_revision_id: UUID
    source_attempt_verdict: str
    source_finished_at: datetime
    policy_fingerprint: str
    created_at: datetime
    reason: str | None
    active: bool
    activated_at: datetime | None


@dataclass(frozen=True, slots=True)
class ActivationSummary:
    id: UUID
    test_case_id: UUID
    environment_id: UUID
    project_id: UUID
    baseline_id: UUID
    baseline_version: int
    activated_at: datetime
    deactivated_at: datetime | None
    reason: str | None


@dataclass(frozen=True, slots=True)
class SourceAssessment:
    source_attempt_id: UUID
    source_execution_id: UUID
    source_test_case_revision_id: UUID
    project_id: UUID
    source_attempt_verdict: str
    source_finished_at: datetime
    policy_fingerprint: str
    selected_values: dict[str, object]
    warning_codes: tuple[str, ...]
    ineligibility_codes: tuple[str, ...]

    @property
    def eligible(self) -> bool:
        return not self.ineligibility_codes


@dataclass(frozen=True, slots=True)
class BaselineCreateResult:
    baseline: BaselineSummary
    activation: ActivationSummary
    etag: str
    created: bool


@dataclass(frozen=True, slots=True)
class BaselineActivationResult:
    activation: ActivationSummary
    etag: str
    created: bool


@dataclass(frozen=True, slots=True)
class BaselinePage:
    items: tuple[BaselineSummary, ...]
    next_after: tuple[int, UUID] | None
    etag: str


def _validate_reason_or_raise(reason: str | None) -> None:
    try:
        validate_reason(reason)
    except PersistenceValidationError as error:
        raise BaselineValidationError from error


def _validate_acknowledgements(warnings: tuple[str, ...], acknowledged: Sequence[str]) -> None:
    received = tuple(acknowledged)
    if received != tuple(sorted(set(received))) or received != warnings:
        raise BaselineConfirmationRequired


class BaselineService:
    """Coordinates immutable baseline commands through a caller-owned UoW."""

    def __init__(
        self,
        unit_of_work: Callable[[], BaselineUnitOfWork],
        *,
        ids: Callable[[], UUID],
        clock: Callable[[], datetime],
    ) -> None:
        self._unit_of_work = unit_of_work
        self._ids = ids
        self._clock = clock

    def promote(
        self,
        scope: BaselineScope,
        *,
        source_attempt_id: UUID,
        reason: str | None,
        confirmation: str,
        acknowledged_warnings: Sequence[str],
        if_match: str,
    ) -> BaselineCreateResult:
        _validate_reason_or_raise(reason)
        try:
            parsed = parse_scope_etag(if_match, scope)
        except (ScopeETagError, ValueError) as error:
            raise BaselineRevisionConflict from error

        with self._unit_of_work() as unit:
            repository = unit.baselines
            state = repository.get_scope(scope, for_update=True)
            if state is None:
                raise BaselineNotFound

            existing = repository.get_by_source_attempt(source_attempt_id)
            if existing is not None:
                if (existing.test_case_id, existing.environment_id) != (
                    scope.test_case_id,
                    scope.environment_id,
                ):
                    raise BaselineNotFound
                if existing.reason != reason:
                    raise BaselineResourceConflict
                if confirmation != _CONFIRMATION:
                    raise BaselineResourceConflict
                assessment = repository.get_source_assessment(
                    scope,
                    source_attempt_id,
                    current_policy_fingerprint=repository.current_policy_fingerprint(scope),
                )
                if (
                    assessment is not None
                    and tuple(acknowledged_warnings) != assessment.warning_codes
                ):
                    raise BaselineResourceConflict
                initial = repository.get_initial_activation(existing.id)
                if initial is None:
                    raise RuntimeError("baseline promotion lost its initial activation")
                return BaselineCreateResult(
                    baseline=existing,
                    activation=initial,
                    etag=make_scope_etag(scope, state),
                    created=False,
                )

            if parsed.digest != make_scope_etag(scope, state).split(":")[-1].rstrip('"'):
                raise BaselineRevisionConflict
            if confirmation != _CONFIRMATION:
                raise BaselineConfirmationRequired
            assessment = repository.get_source_assessment(
                scope,
                source_attempt_id,
                current_policy_fingerprint=repository.current_policy_fingerprint(scope),
            )
            if assessment is None:
                raise BaselineNotFound
            _validate_acknowledgements(assessment.warning_codes, acknowledged_warnings)
            if "policy_mismatch" in assessment.ineligibility_codes:
                raise BaselineIncompatible
            if not assessment.eligible:
                raise BaselineIneligible(assessment.ineligibility_codes)

            now = self._clock()
            baseline = BaselineSummary(
                id=self._ids(),
                test_case_id=scope.test_case_id,
                environment_id=scope.environment_id,
                project_id=assessment.project_id,
                version=state.latest_version + 1,
                source_attempt_id=assessment.source_attempt_id,
                source_execution_id=assessment.source_execution_id,
                source_test_case_revision_id=assessment.source_test_case_revision_id,
                source_attempt_verdict=assessment.source_attempt_verdict,
                source_finished_at=assessment.source_finished_at,
                policy_fingerprint=assessment.policy_fingerprint,
                created_at=now,
                reason=reason,
                active=True,
                activated_at=now,
            )
            activation = ActivationSummary(
                id=self._ids(),
                test_case_id=scope.test_case_id,
                environment_id=scope.environment_id,
                project_id=assessment.project_id,
                baseline_id=baseline.id,
                baseline_version=baseline.version,
                activated_at=now,
                deactivated_at=None,
                reason=None,
            )
            current = repository.current_activation(scope)
            if current is not None:
                repository.close_current_activation(current.id, at=now)
            repository.add_baseline(baseline, selected_values=assessment.selected_values)
            repository.add_activation(activation)
            unit.add_change(
                self._activation_event(
                    self._ids(),
                    assessment.project_id,
                    baseline,
                    activation,
                    now,
                    before_ref=current.id if current else None,
                )
            )
            unit.commit()
            return BaselineCreateResult(
                baseline=baseline,
                activation=activation,
                etag=make_scope_etag(
                    scope,
                    ScopeState(baseline.version, activation.id),
                ),
                created=True,
            )

    def activate(
        self,
        scope: BaselineScope,
        *,
        baseline_id: UUID,
        reason: str | None,
        if_match: str,
    ) -> BaselineActivationResult:
        _validate_reason_or_raise(reason)
        try:
            parsed = parse_scope_etag(if_match, scope)
        except (ScopeETagError, ValueError) as error:
            raise BaselineRevisionConflict from error
        with self._unit_of_work() as unit:
            repository = unit.baselines
            state = repository.get_scope(scope, for_update=True)
            if state is None:
                raise BaselineNotFound
            current_etag = make_scope_etag(scope, state)
            if parsed.digest != current_etag.split(":")[-1].rstrip('"'):
                raise BaselineRevisionConflict
            baseline = repository.get(scope, baseline_id)
            if baseline is None:
                raise BaselineNotFound
            if baseline.policy_fingerprint != repository.current_policy_fingerprint(scope):
                raise BaselineIncompatible
            current = repository.current_activation(scope)
            if current is not None and current.baseline_id == baseline.id:
                return BaselineActivationResult(current, current_etag, False)

            now = self._clock()
            if current is not None:
                repository.close_current_activation(current.id, at=now)
            activation = ActivationSummary(
                id=self._ids(),
                test_case_id=scope.test_case_id,
                environment_id=scope.environment_id,
                project_id=baseline.project_id,
                baseline_id=baseline.id,
                baseline_version=baseline.version,
                activated_at=now,
                deactivated_at=None,
                reason=reason,
            )
            repository.add_activation(activation)
            unit.add_change(
                self._activation_event(
                    self._ids(),
                    baseline.project_id,
                    baseline,
                    activation,
                    now,
                    before_ref=current.id if current else None,
                )
            )
            unit.commit()
            return BaselineActivationResult(
                activation=activation,
                etag=make_scope_etag(scope, ScopeState(state.latest_version, activation.id)),
                created=True,
            )

    def list_history(
        self,
        scope: BaselineScope,
        *,
        after: tuple[int, UUID] | None,
        limit: int,
    ) -> BaselinePage:
        if not 1 <= limit <= 100:
            raise BaselineValidationError
        with self._unit_of_work() as unit:
            repository = unit.baselines
            state = repository.get_scope(scope)
            if state is None:
                raise BaselineNotFound
            rows = tuple(repository.list(scope, after=after, limit=limit + 1))
            next_after = (
                (rows[limit - 1].version, rows[limit - 1].id) if len(rows) > limit else None
            )
            return BaselinePage(
                items=rows[:limit],
                next_after=next_after,
                etag=make_scope_etag(scope, state),
            )

    @staticmethod
    def _activation_event(
        event_id: UUID,
        project_id: UUID,
        baseline: BaselineSummary,
        activation: ActivationSummary,
        created_at: datetime,
        *,
        before_ref: UUID | None = None,
    ) -> ChangeEvent:
        from sentinel.catalog.changes import (
            ChangeEvent,
            ChangeEventKind,
            ChangeSubjectType,
            ChangeSummary,
        )

        return ChangeEvent(
            id=event_id,
            project_id=project_id,
            kind=ChangeEventKind.BASELINE_ACTIVATED,
            subject_type=ChangeSubjectType.BASELINE,
            subject_id=baseline.id,
            before_ref=before_ref,
            after_ref=activation.id,
            summary=ChangeSummary.from_values(["baseline_activation"]),
            created_at=created_at,
        )

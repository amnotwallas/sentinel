"""Typed persistence inputs and bounded validation for M4 regression results."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Literal
from uuid import UUID

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from sentinel.persistence.models import (
    BaselineActivationRow,
    BaselineComparisonRow,
    BaselineRow,
    EnvironmentRow,
    EvaluationRow,
    ExecutionItemRow,
    ExecutionRow,
    ProjectRow,
    TestAttemptRow,
    TestCaseRevisionRow,
    TestCaseRow,
)

if TYPE_CHECKING:
    from sentinel.regression.baselines import (
        ActivationSummary,
        BaselineScope,
        BaselineSummary,
        ScopeState,
        SourceAssessment,
    )
    from sentinel.regression.ports import BaselineRepository
from sentinel.regression.policy import canonical_json

MAX_EVALUATION_EVIDENCE_BYTES = 4096
MAX_BASELINE_VALUE_BYTES = 4096
MAX_BASELINE_DOCUMENT_BYTES = 1_048_576
MAX_BASELINE_VALUES = 128
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_REDACTED = "[REDACTED]"


class PersistenceValidationError(ValueError):
    """A persistence input cannot satisfy the frozen M4 storage contract."""


@dataclass(frozen=True, slots=True)
class BoundedEvidence:
    value: object | None
    omitted: bool


@dataclass(frozen=True, slots=True)
class BaselineComparisonInput:
    state: Literal["not_requested", "missing", "incompatible", "compatible"]
    baseline_activation_id: UUID | None
    baseline_id: UUID | None
    baseline_version: int | None
    policy_fingerprint: str | None
    checked_at: datetime


@dataclass(frozen=True, slots=True)
class EvaluationInput:
    id: UUID
    ordinal: int
    kind: Literal["assertion", "baseline_selector", "performance"]
    rule_id: UUID | None
    severity: Literal["required", "advisory"]
    outcome: Literal["passed", "failed", "unevaluable", "not_evaluated"]
    message_code: str
    expected: BoundedEvidence
    actual: BoundedEvidence
    created_at: datetime


@dataclass(frozen=True, slots=True)
class BaselineInput:
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
    selected_values: Mapping[str, object]
    reason: str | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class BaselineActivationInput:
    id: UUID
    test_case_id: UUID
    environment_id: UUID
    project_id: UUID
    baseline_id: UUID
    activated_at: datetime
    reason: str | None


def _canonical_bytes(value: object) -> int:
    try:
        return len(canonical_json(value).encode("utf-8"))
    except Exception as exc:
        raise PersistenceValidationError("value is not canonically representable") from exc


def bounded_evidence(value: object) -> BoundedEvidence:
    """Keep an evidence value whole or omit it; never persist a misleading prefix."""

    return BoundedEvidence(
        value=value if _canonical_bytes(value) <= MAX_EVALUATION_EVIDENCE_BYTES else None,
        omitted=_canonical_bytes(value) > MAX_EVALUATION_EVIDENCE_BYTES,
    )


def validate_reason(reason: str | None) -> None:
    if reason is None:
        return
    if not 1 <= len(reason.encode("utf-8")) <= 500 or any(
        ord(character) < 0x20 or ord(character) == 0x7F for character in reason
    ):
        raise PersistenceValidationError("reason is outside the bounded text contract")


def validate_sha256(value: str) -> None:
    if _SHA256.fullmatch(value) is None:
        raise PersistenceValidationError("fingerprint must be lowercase SHA-256")


def validate_selected_values(document: object) -> None:
    if not isinstance(document, Mapping) or set(document) != {"schema_version", "values"}:
        raise PersistenceValidationError("selected values document shape is invalid")
    if document.get("schema_version") != 1 or not isinstance(document.get("values"), list):
        raise PersistenceValidationError("selected values document schema is invalid")
    values = document["values"]
    if len(values) > MAX_BASELINE_VALUES:
        raise PersistenceValidationError("selected values entry limit exceeded")
    identifiers: set[str] = set()
    for entry in values:
        if not isinstance(entry, Mapping) or set(entry) != {"rule_id", "value"}:
            raise PersistenceValidationError("selected value entry shape is invalid")
        identifier = entry["rule_id"]
        if not isinstance(identifier, str):
            raise PersistenceValidationError("selected value rule id is invalid")
        try:
            parsed = UUID(identifier)
        except ValueError:
            raise PersistenceValidationError("selected value rule id is invalid") from None
        if str(parsed) != identifier or identifier in identifiers:
            raise PersistenceValidationError("selected value rule ids must be unique and canonical")
        identifiers.add(identifier)
        if _canonical_bytes(entry["value"]) > MAX_BASELINE_VALUE_BYTES:
            raise PersistenceValidationError("selected value limit exceeded")
    if _canonical_bytes(document) > MAX_BASELINE_DOCUMENT_BYTES:
        raise PersistenceValidationError("selected values document limit exceeded")


def validate_evaluation_input(value: EvaluationInput) -> None:
    if not 0 <= value.ordinal <= 256:
        raise PersistenceValidationError("evaluation ordinal is outside the contract")
    if value.kind == "performance" and value.rule_id is not None:
        raise PersistenceValidationError("performance evaluations cannot have a rule id")
    if value.kind != "performance" and value.rule_id is None:
        raise PersistenceValidationError("non-performance evaluations require a rule id")
    if value.kind == "performance" and value.severity != "advisory":
        raise PersistenceValidationError("performance evaluations are advisory")


class PostgresEvaluationPersistence:
    """Adds bounded result rows to a caller-owned transaction.

    The caller owns attempt fencing and state transitions; this class only supplies
    the atomic child-row materialization used by the later orchestration slice.
    """

    @staticmethod
    def add_result(
        session: Session,
        *,
        attempt_id: UUID,
        comparison: BaselineComparisonInput,
        evaluations: Sequence[EvaluationInput],
    ) -> None:
        if len(evaluations) > 257:
            raise PersistenceValidationError("evaluation count exceeds the contract")
        if len({evaluation.ordinal for evaluation in evaluations}) != len(evaluations):
            raise PersistenceValidationError("evaluation ordinals must be unique")
        for evaluation in evaluations:
            validate_evaluation_input(evaluation)
        if comparison.state in {"not_requested", "missing"} and any(
            value is not None
            for value in (
                comparison.baseline_activation_id,
                comparison.baseline_id,
                comparison.baseline_version,
                comparison.policy_fingerprint,
            )
        ):
            raise PersistenceValidationError("comparison references are invalid for this state")
        if comparison.state in {"incompatible", "compatible"}:
            if (
                comparison.baseline_activation_id is None
                or comparison.baseline_id is None
                or comparison.baseline_version is None
                or comparison.policy_fingerprint is None
            ):
                raise PersistenceValidationError("comparison references are incomplete")
            validate_sha256(comparison.policy_fingerprint)
        session.add(
            BaselineComparisonRow(
                attempt_id=attempt_id,
                state=comparison.state,
                baseline_activation_id=comparison.baseline_activation_id,
                baseline_id=comparison.baseline_id,
                baseline_version=comparison.baseline_version,
                policy_fingerprint=comparison.policy_fingerprint,
                checked_at=comparison.checked_at,
            )
        )
        session.add_all(
            EvaluationRow(
                id=evaluation.id,
                attempt_id=attempt_id,
                ordinal=evaluation.ordinal,
                kind=evaluation.kind,
                rule_id=evaluation.rule_id,
                severity=evaluation.severity,
                outcome=evaluation.outcome,
                message_code=evaluation.message_code,
                expected=evaluation.expected.value,
                actual=evaluation.actual.value,
                evidence_omitted=evaluation.expected.omitted or evaluation.actual.omitted,
                created_at=evaluation.created_at,
            )
            for evaluation in evaluations
        )


class PostgresBaselinePersistence:
    """Adds immutable baseline rows to a caller-owned transaction.

    Version allocation, scope locking, and activation policy remain application-service
    responsibilities in M4-04; this writer supplies bounded typed row materialization.
    """

    @staticmethod
    def add_baseline(session: Session, value: BaselineInput) -> None:
        if value.version < 1:
            raise PersistenceValidationError("baseline version must be positive")
        validate_sha256(value.policy_fingerprint)
        validate_selected_values(value.selected_values)
        validate_reason(value.reason)
        session.add(
            BaselineRow(
                id=value.id,
                test_case_id=value.test_case_id,
                environment_id=value.environment_id,
                project_id=value.project_id,
                version=value.version,
                source_attempt_id=value.source_attempt_id,
                source_execution_id=value.source_execution_id,
                source_test_case_revision_id=value.source_test_case_revision_id,
                source_attempt_verdict=value.source_attempt_verdict,
                source_finished_at=value.source_finished_at,
                policy_fingerprint=value.policy_fingerprint,
                selected_values_schema_version=1,
                selected_values=dict(value.selected_values),
                reason=value.reason,
                created_at=value.created_at,
            )
        )

    @staticmethod
    def add_activation(session: Session, value: BaselineActivationInput) -> None:
        validate_reason(value.reason)
        session.add(
            BaselineActivationRow(
                id=value.id,
                test_case_id=value.test_case_id,
                environment_id=value.environment_id,
                project_id=value.project_id,
                baseline_id=value.baseline_id,
                activated_at=value.activated_at,
                reason=value.reason,
            )
        )


class PostgresBaselineRepository:
    """Repository for M4-04 commands; all mutations remain in the UoW transaction."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_scope(self, scope: BaselineScope, *, for_update: bool = False) -> ScopeState | None:
        from sentinel.regression.baselines import (
            ActivationSummary,
            ScopeState,
        )

        statement = select(TestCaseRow).where(TestCaseRow.id == scope.test_case_id)
        if for_update:
            statement = statement.with_for_update()
        test_case = self._session.scalar(statement)
        if test_case is None:
            return None
        project = self._session.get(ProjectRow, test_case.project_id)
        environment = self._session.get(EnvironmentRow, scope.environment_id)
        revision = self._session.get(TestCaseRevisionRow, test_case.active_revision_id)
        if (
            project is None
            or project.deleted_at is not None
            or environment is None
            or environment.project_id != test_case.project_id
            or revision is None
            or revision.test_case_id != test_case.id
        ):
            return None
        current = self.current_activation(scope)
        latest = self._session.scalar(
            select(func.max(BaselineRow.version)).where(
                BaselineRow.test_case_id == scope.test_case_id,
                BaselineRow.environment_id == scope.environment_id,
            )
        )
        if latest is None:
            latest = 0
        return ScopeState(
            latest_version=int(latest),
            current_activation_id=current.id if isinstance(current, ActivationSummary) else None,
        )

    def current_policy_fingerprint(self, scope: BaselineScope) -> str:
        from sentinel.regression.baselines import BaselineScope

        assert isinstance(scope, BaselineScope)
        test_case = self._session.get(TestCaseRow, scope.test_case_id)
        if test_case is None:
            raise RuntimeError("test case scope is missing")
        revision = self._session.get(TestCaseRevisionRow, test_case.active_revision_id)
        if revision is None:
            raise RuntimeError("active test case revision is missing")
        return revision.policy_fingerprint

    def current_activation(self, scope: BaselineScope) -> ActivationSummary | None:
        from sentinel.regression.baselines import BaselineScope

        assert isinstance(scope, BaselineScope)
        row = self._session.scalar(
            select(BaselineActivationRow).where(
                BaselineActivationRow.test_case_id == scope.test_case_id,
                BaselineActivationRow.environment_id == scope.environment_id,
                BaselineActivationRow.deactivated_at.is_(None),
            )
        )
        if row is None:
            return None
        baseline = self._session.get(BaselineRow, row.baseline_id)
        if baseline is None:
            raise RuntimeError("current activation baseline is missing")
        return self._activation_summary(row, baseline.version)

    def get_by_source_attempt(self, source_attempt_id: UUID) -> BaselineSummary | None:
        row = self._session.scalar(
            select(BaselineRow).where(BaselineRow.source_attempt_id == source_attempt_id)
        )
        return None if row is None else self._baseline_summary(row)

    def get_initial_activation(self, baseline_id: UUID) -> ActivationSummary | None:
        row = self._session.scalars(
            select(BaselineActivationRow)
            .where(BaselineActivationRow.baseline_id == baseline_id)
            .order_by(BaselineActivationRow.activated_at, BaselineActivationRow.id)
            .limit(1)
        ).first()
        if row is None:
            return None
        baseline = self._session.get(BaselineRow, baseline_id)
        if baseline is None:
            return None
        return self._activation_summary(row, baseline.version)

    def get(self, scope: BaselineScope, baseline_id: UUID) -> BaselineSummary | None:
        from sentinel.regression.baselines import BaselineScope

        assert isinstance(scope, BaselineScope)
        row = self._session.scalar(
            select(BaselineRow).where(
                BaselineRow.id == baseline_id,
                BaselineRow.test_case_id == scope.test_case_id,
                BaselineRow.environment_id == scope.environment_id,
            )
        )
        return None if row is None else self._baseline_summary(row)

    def get_source_assessment(
        self,
        scope: BaselineScope,
        source_attempt_id: UUID,
        *,
        current_policy_fingerprint: str,
    ) -> SourceAssessment | None:
        from sentinel.regression.baselines import SourceAssessment

        attempt = self._session.scalar(
            select(TestAttemptRow).where(TestAttemptRow.id == source_attempt_id).with_for_update()
        )
        if attempt is None:
            return None
        item = self._session.get(ExecutionItemRow, attempt.execution_item_id)
        execution = self._session.get(ExecutionRow, item.execution_id) if item else None
        revision = (
            self._session.get(TestCaseRevisionRow, item.test_case_revision_id) if item else None
        )
        project = self._session.get(ProjectRow, item.project_id) if item else None
        if (
            item is None
            or execution is None
            or revision is None
            or project is None
            or project.deleted_at is not None
            or item.test_case_id != scope.test_case_id
            or item.project_id != project.id
            or execution.environment_id != scope.environment_id
            or execution.project_id != project.id
            or execution.id != item.execution_id
        ):
            return None

        comparison = self._session.get(BaselineComparisonRow, attempt.id)
        evaluations = list(
            self._session.scalars(
                select(EvaluationRow)
                .where(EvaluationRow.attempt_id == attempt.id)
                .order_by(EvaluationRow.ordinal)
            )
        )
        policy = revision.definition.get("comparison_policy")
        selector_ids: list[str] = []
        if isinstance(policy, dict):
            raw_selectors = policy.get("selectors")
            if isinstance(raw_selectors, list):
                selector_ids.extend(
                    str(value["id"])
                    for value in raw_selectors
                    if isinstance(value, dict) and isinstance(value.get("id"), str)
                )
            text_selector = policy.get("text_body_selector")
            if isinstance(text_selector, dict) and isinstance(text_selector.get("id"), str):
                selector_ids.append(str(text_selector["id"]))

        warnings: list[str] = []
        if comparison is None:
            # A terminal attempt without its comparison row is not promotable.
            comparison_state = None
        else:
            comparison_state = comparison.state
        if comparison is not None and comparison.state == "missing":
            warnings.append("missing_baseline")
        elif comparison is not None and comparison.state == "incompatible":
            warnings.append("incompatible_baseline")
        if attempt.verdict == "observed_change":
            warnings.append("observed_change")
        if attempt.verdict == "performance_warning":
            warnings.append("performance_warning")
        warning_codes = tuple(code for code in _WARNING_ORDER if code in warnings)

        ineligible: list[str] = []
        if not selector_ids:
            ineligible.append("no_selectors")
        if (
            attempt.result_contract_version != 1
            or attempt.state != "evaluated"
            or attempt.verdict is None
            or attempt.finished_at is None
        ):
            ineligible.append("attempt_not_evaluated")
        if not attempt.included_in_verdict:
            ineligible.append("attempt_not_included")
        if attempt.verdict == "functional_regression":
            ineligible.append("required_functional_check_failed")
        if attempt.verdict == "inconclusive" or attempt.evaluation_error_code is not None:
            ineligible.append("evaluation_inconclusive")
        if comparison_state is None or (selector_ids and comparison_state == "not_requested"):
            ineligible.append("evaluation_inconclusive")
        if attempt.verdict == "baseline_required" and not {
            "missing_baseline",
            "incompatible_baseline",
        }.intersection(warning_codes):
            ineligible.append("evaluation_inconclusive")
        if revision.policy_fingerprint != current_policy_fingerprint:
            ineligible.append("policy_mismatch")

        by_rule = {
            str(row.rule_id): row
            for row in evaluations
            if row.kind == "baseline_selector" and row.rule_id is not None
        }
        values: list[dict[str, object]] = []
        unavailable = {
            "content_missing",
            "content_expired",
            "content_truncated",
            "content_redacted",
            "normalizer_input_invalid",
            "invalid_json",
        }
        for rule_id in selector_ids:
            row = by_rule.get(rule_id)
            if row is None:
                ineligible.append("selected_value_unavailable")
                continue
            if row.message_code in unavailable:
                ineligible.append("selected_value_unavailable")
                continue
            if _contains_redacted(row.actual):
                ineligible.append("selected_value_unavailable")
                continue
            if row.evidence_omitted:
                ineligible.append("selected_value_too_large")
                continue
            values.append({"rule_id": rule_id, "value": row.actual})
        selected_values = {"schema_version": 1, "values": values}
        ineligible = [code for code in _INELIGIBILITY_ORDER if code in ineligible]
        assert attempt.finished_at is not None
        return SourceAssessment(
            source_attempt_id=attempt.id,
            source_execution_id=execution.id,
            source_test_case_revision_id=revision.id,
            project_id=project.id,
            source_attempt_verdict=attempt.verdict or "not_evaluated",
            source_finished_at=attempt.finished_at,
            policy_fingerprint=revision.policy_fingerprint,
            selected_values=selected_values,
            warning_codes=warning_codes,
            ineligibility_codes=tuple(ineligible),
        )

    def list(
        self,
        scope: BaselineScope,
        *,
        after: tuple[int, UUID] | None,
        limit: int,
    ) -> list[BaselineSummary]:
        from sentinel.regression.baselines import BaselineScope

        assert isinstance(scope, BaselineScope)
        statement = select(BaselineRow).where(
            BaselineRow.test_case_id == scope.test_case_id,
            BaselineRow.environment_id == scope.environment_id,
        )
        if after is not None:
            version, baseline_id = after
            statement = statement.where(
                or_(
                    BaselineRow.version > version,
                    and_(BaselineRow.version == version, BaselineRow.id > baseline_id),
                )
            )
        rows = self._session.scalars(
            statement.order_by(BaselineRow.version, BaselineRow.id).limit(limit)
        )
        return [self._baseline_summary(row) for row in rows]

    def add_baseline(self, value: BaselineSummary, *, selected_values: dict[str, object]) -> None:
        PostgresBaselinePersistence.add_baseline(
            self._session,
            BaselineInput(
                id=value.id,
                test_case_id=value.test_case_id,
                environment_id=value.environment_id,
                project_id=value.project_id,
                version=value.version,
                source_attempt_id=value.source_attempt_id,
                source_execution_id=value.source_execution_id,
                source_test_case_revision_id=value.source_test_case_revision_id,
                source_attempt_verdict=value.source_attempt_verdict,
                source_finished_at=value.source_finished_at,
                policy_fingerprint=value.policy_fingerprint,
                selected_values=selected_values,
                reason=value.reason,
                created_at=value.created_at,
            ),
        )
        self._session.flush()

    def add_activation(self, value: ActivationSummary) -> None:
        PostgresBaselinePersistence.add_activation(
            self._session,
            BaselineActivationInput(
                id=value.id,
                test_case_id=value.test_case_id,
                environment_id=value.environment_id,
                project_id=value.project_id,
                baseline_id=value.baseline_id,
                activated_at=value.activated_at,
                reason=value.reason,
            ),
        )

    def close_current_activation(self, activation_id: UUID, *, at: datetime) -> None:
        self._session.execute(
            update(BaselineActivationRow)
            .where(
                BaselineActivationRow.id == activation_id,
                BaselineActivationRow.deactivated_at.is_(None),
            )
            .values(deactivated_at=at)
        )

    def _baseline_summary(self, row: BaselineRow) -> BaselineSummary:
        from sentinel.regression.baselines import BaselineSummary

        activation = self._session.scalar(
            select(BaselineActivationRow).where(
                BaselineActivationRow.test_case_id == row.test_case_id,
                BaselineActivationRow.environment_id == row.environment_id,
                BaselineActivationRow.baseline_id == row.id,
                BaselineActivationRow.deactivated_at.is_(None),
            )
        )
        # The current flag is deliberately queried by identity, not inferred from history.
        return BaselineSummary(
            id=row.id,
            test_case_id=row.test_case_id,
            environment_id=row.environment_id,
            project_id=row.project_id,
            version=row.version,
            source_attempt_id=row.source_attempt_id,
            source_execution_id=row.source_execution_id,
            source_test_case_revision_id=row.source_test_case_revision_id,
            source_attempt_verdict=row.source_attempt_verdict,
            source_finished_at=row.source_finished_at,
            policy_fingerprint=row.policy_fingerprint,
            created_at=row.created_at,
            reason=row.reason,
            active=activation is not None,
            activated_at=activation.activated_at if activation else None,
        )

    def _activation_summary(self, row: BaselineActivationRow, version: int) -> ActivationSummary:
        from sentinel.regression.baselines import ActivationSummary

        return ActivationSummary(
            id=row.id,
            test_case_id=row.test_case_id,
            environment_id=row.environment_id,
            project_id=row.project_id,
            baseline_id=row.baseline_id,
            baseline_version=version,
            activated_at=row.activated_at,
            deactivated_at=row.deactivated_at,
            reason=row.reason,
        )


_WARNING_ORDER = (
    "missing_baseline",
    "incompatible_baseline",
    "observed_change",
    "performance_warning",
)
_INELIGIBILITY_ORDER = (
    "no_selectors",
    "attempt_not_evaluated",
    "attempt_not_included",
    "required_functional_check_failed",
    "evaluation_inconclusive",
    "selected_value_unavailable",
    "selected_value_too_large",
    "policy_mismatch",
    "scope_mismatch",
)


def _contains_redacted(value: object) -> bool:
    if isinstance(value, str) and _REDACTED in value:
        return True
    if isinstance(value, list):
        return any(_contains_redacted(item) for item in value)
    if isinstance(value, Mapping):
        return any(_contains_redacted(item) for item in value.values())
    return False


class PostgresBaselineUnitOfWork:
    """One command transaction; repository writers never commit independently."""

    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self._sessions = sessions
        self._session: Session | None = None

    def __enter__(self) -> PostgresBaselineUnitOfWork:
        self._session = self._sessions()
        self.baselines: BaselineRepository = PostgresBaselineRepository(self._session)
        from sentinel.persistence.catalog.changes import SqlAlchemyChangeRepository

        self._changes = SqlAlchemyChangeRepository(self._session)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: object | None,
    ) -> None:
        if self._session is None:
            return
        if exc_type is not None:
            self._session.rollback()
        self._session.close()
        self._session = None

    def add_change(self, event: object) -> None:
        from sentinel.catalog.changes import ChangeEvent

        assert isinstance(event, ChangeEvent)
        self._changes.add(event)

    def commit(self) -> None:
        if self._session is None:
            raise RuntimeError("unit of work is not active")
        try:
            self._session.commit()
        except IntegrityError as error:
            self._session.rollback()
            constraint = getattr(getattr(error.orig, "diag", None), "constraint_name", None)
            if constraint in {"uq_baselines_source_attempt", "uq_baselines_scope_version"}:
                from sentinel.regression.baselines import BaselineResourceConflict

                raise BaselineResourceConflict from None
            raise

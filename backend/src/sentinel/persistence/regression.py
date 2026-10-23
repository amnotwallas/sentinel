"""Typed persistence inputs and bounded validation for M4 regression results."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from sqlalchemy.orm import Session

from sentinel.persistence.models import (
    BaselineActivationRow,
    BaselineComparisonRow,
    BaselineRow,
    EvaluationRow,
)
from sentinel.regression.policy import canonical_json

MAX_EVALUATION_EVIDENCE_BYTES = 4096
MAX_BASELINE_VALUE_BYTES = 4096
MAX_BASELINE_DOCUMENT_BYTES = 1_048_576
MAX_BASELINE_VALUES = 128
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


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

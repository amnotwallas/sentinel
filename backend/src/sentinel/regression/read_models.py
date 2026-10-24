"""Transport-neutral result projections for the M4 read APIs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sentinel.catalog.changes import ChangeEvent


@dataclass(frozen=True, slots=True)
class ComparisonRead:
    state: str
    baseline_activation_id: UUID | None
    baseline_id: UUID | None
    baseline_version: int | None
    policy_fingerprint: str | None
    checked_at: datetime | None


@dataclass(frozen=True, slots=True)
class EvaluationRead:
    id: UUID
    ordinal: int
    kind: str
    rule_id: UUID | None
    severity: str
    outcome: str
    message_code: str
    expected: object | None
    actual: object | None
    evidence_omitted: bool


@dataclass(frozen=True, slots=True)
class PromotionRead:
    eligible: bool
    warning_codes: tuple[str, ...]
    ineligibility_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ChangeRead:
    events: tuple[ChangeEvent, ...]
    truncated: bool = False

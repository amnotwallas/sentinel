from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class JobState(StrEnum):
    PENDING = "pending"
    LEASED = "leased"
    SUCCEEDED = "succeeded"
    DEAD = "dead"


class InvalidTransition(ValueError):
    pass


class LeaseLost(RuntimeError):
    """The lease expired, changed ownership, or reached a terminal state."""


class InfrastructureFailure(RuntimeError):
    """Retryable infrastructure failure; carries no raw driver error or credentials."""


class ErrorCode(StrEnum):
    INFRASTRUCTURE_FAILURE = "infrastructure_failure"
    DELIVERY_EXHAUSTED = "delivery_exhausted"
    HANDLER_NOT_FOUND = "handler_not_found"
    HANDLER_FAILED = "handler_failed"


def validate_transition(source: JobState, target: JobState, *, renewal: bool = False) -> None:
    allowed = {
        JobState.PENDING: {JobState.LEASED, JobState.DEAD},
        JobState.LEASED: {JobState.PENDING, JobState.SUCCEEDED, JobState.DEAD},
        JobState.SUCCEEDED: set(),
        JobState.DEAD: set(),
    }
    if renewal and source == target == JobState.LEASED:
        return
    if target not in allowed[source]:
        raise InvalidTransition(f"invalid job transition: {source} -> {target}")


@dataclass(frozen=True)
class Lease:
    job_id: UUID
    subject_id: UUID
    kind: str
    owner: UUID
    token: UUID
    expires_at: datetime
    delivery_count: int


@dataclass(frozen=True)
class Probe:
    execution_id: UUID
    job_id: UUID

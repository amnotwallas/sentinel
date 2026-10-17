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


class AttemptState(StrEnum):
    PREPARED = "prepared"
    DISPATCHING = "dispatching"
    RESPONSE_RECEIVED = "response_received"
    TRANSPORT_FAILED = "transport_failed"
    EVALUATED = "evaluated"
    REPLAY_SCHEDULED = "replay_scheduled"
    INDETERMINATE = "indeterminate"
    FAILED = "failed"


class DispatchCertainty(StrEnum):
    NOT_STARTED = "not_started"
    NOT_SENT = "not_sent"
    POSSIBLY_SENT = "possibly_sent"
    RESPONSE_RECEIVED = "response_received"


class TransportOutcome(StrEnum):
    RESPONSE_RECEIVED = "response_received"
    DNS_FAILURE = "dns_failure"
    CONNECT_TIMEOUT = "connect_timeout"
    CONNECTION_FAILURE = "connection_failure"
    TLS_FAILURE = "tls_failure"
    WRITE_TIMEOUT = "write_timeout"
    WRITE_FAILURE = "write_failure"
    READ_TIMEOUT = "read_timeout"
    READ_FAILURE = "read_failure"
    TOTAL_TIMEOUT = "total_timeout"
    TARGET_DENIED = "target_denied"
    REDIRECT_DENIED = "redirect_denied"
    RESPONSE_LIMIT_EXCEEDED = "response_limit_exceeded"
    INDETERMINATE = "indeterminate"


class PreparationErrorCode(StrEnum):
    SECRET_MISSING = "secret_missing"
    TEMPLATE_VARIABLE_MISSING = "template_variable_missing"
    TARGET_POLICY_DENIED = "target_policy_denied"
    REQUEST_INVALID = "request_invalid"
    TLS_VERIFICATION_REQUIRED = "tls_verification_required"
    INFRASTRUCTURE_FAILURE = "infrastructure_failure"


class RedirectRejectionCode(StrEnum):
    METHOD_NOT_ALLOWED = "method_not_allowed"
    LOCATION_MISSING = "location_missing"
    LOCATION_INVALID = "location_invalid"
    SCHEME_DENIED = "scheme_denied"
    PORT_DENIED = "port_denied"
    TARGET_DENIED = "target_denied"
    REDIRECT_LIMIT_EXCEEDED = "redirect_limit_exceeded"


class AttemptInvalidTransition(ValueError):
    pass


_ATTEMPT_TRANSITIONS: dict[AttemptState, frozenset[AttemptState]] = {
    AttemptState.PREPARED: frozenset({AttemptState.FAILED, AttemptState.DISPATCHING}),
    AttemptState.DISPATCHING: frozenset(
        {
            AttemptState.RESPONSE_RECEIVED,
            AttemptState.TRANSPORT_FAILED,
            AttemptState.REPLAY_SCHEDULED,
            AttemptState.INDETERMINATE,
        }
    ),
    AttemptState.RESPONSE_RECEIVED: frozenset({AttemptState.EVALUATED, AttemptState.FAILED}),
    AttemptState.TRANSPORT_FAILED: frozenset(),
    AttemptState.EVALUATED: frozenset(),
    AttemptState.REPLAY_SCHEDULED: frozenset(),
    AttemptState.INDETERMINATE: frozenset(),
    AttemptState.FAILED: frozenset(),
}


def validate_attempt_transition(source: AttemptState, target: AttemptState) -> None:
    if target not in _ATTEMPT_TRANSITIONS[source]:
        raise AttemptInvalidTransition(f"invalid attempt transition: {source} -> {target}")


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
